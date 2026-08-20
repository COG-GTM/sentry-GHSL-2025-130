import hashlib
import hmac
import logging
from abc import ABC
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

import orjson
import sentry_sdk
from django.db import IntegrityError, router, transaction
from django.http import Http404, HttpRequest, HttpResponse
from django.http.response import HttpResponseBase
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

from sentry.api.api_owners import ApiOwner
from sentry.api.api_publish_status import ApiPublishStatus
from sentry.api.base import Endpoint
from sentry.api.exceptions import BadRequest, SentryAPIException
from sentry.integrations.base import IntegrationDomain
from sentry.integrations.models.integration import Integration
from sentry.integrations.source_code_management.webhook import SCMWebhook
from sentry.integrations.types import IntegrationProviderSlug
from sentry.integrations.utils.metrics import IntegrationWebhookEvent, IntegrationWebhookEventType
from sentry.models.commit import Commit
from sentry.models.commitauthor import CommitAuthor
from sentry.models.organization import Organization
from sentry.models.repository import Repository
from sentry.plugins.providers import IntegrationRepositoryProvider
from sentry.shared_integrations.exceptions import ApiHostError, ApiUnauthorized, IntegrationError
from sentry.web.frontend.base import region_silo_view

logger = logging.getLogger("sentry.webhooks")

PROVIDER_NAME = "integrations:bitbucket_server"


def get_repository_payload(event: Mapping[str, Any]) -> Mapping[str, Any]:
    repository = event.get("repository")
    return repository if isinstance(repository, dict) else {}


def is_valid_signature(body: bytes, secret: str, signature: str) -> bool:
    expected_signature = hmac.new(
        secret.encode("utf-8"),
        msg=body,
        digestmod=hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected_signature, signature)


class WebhookMissingSecretException(SentryAPIException):
    status_code = 401
    code = f"{PROVIDER_NAME}.webhook.missing-secret"
    message = "No webhook secret is configured for this repository"


class WebhookMissingSignatureException(SentryAPIException):
    status_code = 400
    code = f"{PROVIDER_NAME}.webhook.missing-signature"
    message = "Missing webhook signature"


class WebhookUnsupportedSignatureMethodException(SentryAPIException):
    status_code = 400
    code = f"{PROVIDER_NAME}.webhook.unsupported-signature-method"
    message = "Signature method is not supported"


class WebhookInvalidSignatureException(SentryAPIException):
    status_code = 400
    code = f"{PROVIDER_NAME}.webhook.invalid-signature"
    message = "Webhook signature is invalid"


class BitbucketServerWebhook(SCMWebhook, ABC):
    @property
    def provider(self):
        return IntegrationProviderSlug.BITBUCKET_SERVER.value

    def update_repo_data(self, repo, event):
        """
        Given a webhook payload, update stored repo data if needed.
        """

        repository = get_repository_payload(event)
        project = repository.get("project")
        project_key = project.get("key") if isinstance(project, dict) else None
        slug = repository.get("slug")

        # A project key or slug containing a separator would make the stored name
        # ambiguous, since the name is split on "/" to address the repository.
        if (
            not isinstance(project_key, str)
            or not isinstance(slug, str)
            or not project_key
            or not slug
            or "/" in project_key
            or "/" in slug
        ):
            logger.warning(
                "%s.webhook.invalid-repository-name",
                PROVIDER_NAME,
                extra={"repository_id": repo.id, "organization_id": repo.organization_id},
            )
            return

        name_from_event = f"{project_key}/{slug}"
        if (
            repo.name != name_from_event
            or repo.config.get("name") != name_from_event
            or repo.config.get("project") != project_key
            or repo.config.get("repo") != slug
        ):
            repo.update(
                name=name_from_event,
                config=dict(repo.config, name=name_from_event, project=project_key, repo=slug),
            )


class PushEventWebhook(BitbucketServerWebhook):
    @property
    def event_type(self) -> IntegrationWebhookEventType:
        return IntegrationWebhookEventType.PUSH

    def __call__(self, event: Mapping[str, Any], **kwargs) -> None:
        authors = {}

        if not (
            (organization := kwargs.get("organization"))
            and (integration_id := kwargs.get("integration_id"))
            and (repo := kwargs.get("repo"))
        ):
            raise ValueError("Organization, integration_id and repo must be provided")

        with IntegrationWebhookEvent(
            interaction_type=self.event_type,
            domain=IntegrationDomain.SOURCE_CODE_MANAGEMENT,
            provider_key=self.provider,
        ).capture() as lifecycle:
            provider = repo.get_provider()
            try:
                installation = provider.get_installation(integration_id, organization.id)
            except Integration.DoesNotExist as e:
                lifecycle.record_halt(halt_reason=e)
                raise Http404()

            try:
                client = installation.get_client()
            except IntegrationError as e:
                lifecycle.record_halt(halt_reason=e)
                raise BadRequest()

            # while we're here, make sure repo data is up to date
            self.update_repo_data(repo, event)

            project_name = repo.config.get("project")
            repo_name = repo.config.get("repo")
            if not project_name or not repo_name:
                name_parts = repo.name.split("/")
                if len(name_parts) != 2:
                    lifecycle.record_halt(halt_reason="invalid-repository-name")
                    raise BadRequest(detail="Invalid repository name")
                project_name, repo_name = name_parts

            for change in event["changes"]:
                from_hash = None if change.get("fromHash") == "0" * 40 else change.get("fromHash")
                try:
                    commits = client.get_commits(
                        project_name, repo_name, from_hash, change.get("toHash")
                    )
                except ApiHostError as e:
                    lifecycle.record_halt(halt_reason=e)
                    raise BadRequest(detail="Unable to reach host")
                except ApiUnauthorized as e:
                    lifecycle.record_halt(halt_reason=e)
                    raise BadRequest()
                except Exception as e:
                    sentry_sdk.capture_exception(e)
                    raise

                for commit in commits:
                    if IntegrationRepositoryProvider.should_ignore_commit(commit["message"]):
                        continue

                    author_email = commit["author"]["emailAddress"]

                    # its optional, lets just throw it out for now
                    if author_email is None or len(author_email) > 75:
                        author = None
                    elif author_email not in authors:
                        authors[author_email] = author = CommitAuthor.objects.get_or_create(
                            organization_id=organization.id,
                            email=author_email,
                            defaults={"name": commit["author"]["name"]},
                        )[0]
                    else:
                        author = authors[author_email]
                    try:
                        with transaction.atomic(router.db_for_write(Commit)):
                            Commit.objects.create(
                                repository_id=repo.id,
                                organization_id=organization.id,
                                key=commit["id"],
                                message=commit["message"],
                                author=author,
                                date_added=datetime.fromtimestamp(
                                    commit["authorTimestamp"] / 1000, timezone.utc
                                ),
                            )

                    except IntegrityError:
                        pass


@region_silo_view
class BitbucketServerWebhookEndpoint(Endpoint):
    authentication_classes = ()
    permission_classes = ()
    owner = ApiOwner.ECOSYSTEM
    publish_status = {
        "POST": ApiPublishStatus.PRIVATE,
    }

    _handlers: dict[str, type[BitbucketServerWebhook]] = {"repo:refs_changed": PushEventWebhook}

    def get_handler(self, event_type) -> type[BitbucketServerWebhook] | None:
        return self._handlers.get(event_type)

    @method_decorator(csrf_exempt)
    def dispatch(self, request: HttpRequest, *args, **kwargs) -> HttpResponseBase:
        if request.method != "POST":
            return HttpResponse(status=405)

        return super().dispatch(request, *args, **kwargs)

    def post(self, request: HttpRequest, organization_id, integration_id) -> HttpResponseBase:
        try:
            organization: Organization = Organization.objects.get_from_cache(id=organization_id)
        except Organization.DoesNotExist:
            logger.exception(
                "%s.webhook.invalid-organization",
                PROVIDER_NAME,
                extra={"organization_id": organization_id, "integration_id": integration_id},
            )
            return HttpResponse(status=400)

        body = bytes(request.body)
        if not body:
            logger.error(
                "%s.webhook.missing-body", PROVIDER_NAME, extra={"organization_id": organization.id}
            )
            return HttpResponse(status=400)

        try:
            handler = self.get_handler(request.META["HTTP_X_EVENT_KEY"])
        except KeyError:
            logger.exception(
                "%s.webhook.missing-event",
                PROVIDER_NAME,
                extra={"organization_id": organization.id, "integration_id": integration_id},
            )
            return HttpResponse(status=400)

        if not handler:
            return HttpResponse(status=204)

        try:
            event = orjson.loads(body)
        except orjson.JSONDecodeError:
            logger.exception(
                "%s.webhook.invalid-json",
                PROVIDER_NAME,
                extra={"organization_id": organization.id, "integration_id": integration_id},
            )
            return HttpResponse(status=400)

        external_id = get_repository_payload(event).get("id")
        if external_id is None:
            logger.error(
                "%s.webhook.missing-repository",
                PROVIDER_NAME,
                extra={"organization_id": organization.id, "integration_id": integration_id},
            )
            return HttpResponse(status=400)

        try:
            repo = Repository.objects.get(
                organization_id=organization.id,
                provider=PROVIDER_NAME,
                external_id=str(external_id),
            )
        except Repository.DoesNotExist:
            raise Http404()

        self.verify_signature(request, repo, body)

        event_handler = handler()

        event_handler(event, organization=organization, integration_id=integration_id, repo=repo)

        return HttpResponse(status=204)

    def verify_signature(self, request: HttpRequest, repo: Repository, body: bytes) -> None:
        """
        Bitbucket Server signs the raw request body with the secret we set on the
        repository webhook when the repository was added to Sentry.
        """

        secret = repo.config.get("webhook_secret")
        if not secret:
            logger.error(
                "%s.webhook.missing-secret",
                PROVIDER_NAME,
                extra={"organization_id": repo.organization_id, "repository_id": repo.id},
            )
            raise WebhookMissingSecretException()

        try:
            method, signature = request.META["HTTP_X_HUB_SIGNATURE"].split("=", 1)
        except (KeyError, ValueError):
            raise WebhookMissingSignatureException()

        if method != "sha256":
            raise WebhookUnsupportedSignatureMethodException()

        if not is_valid_signature(body, secret, signature):
            logger.error(
                "%s.webhook.invalid-signature",
                PROVIDER_NAME,
                extra={"organization_id": repo.organization_id, "repository_id": repo.id},
            )
            raise WebhookInvalidSignatureException()
