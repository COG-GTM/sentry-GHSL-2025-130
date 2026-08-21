from __future__ import annotations

import logging

import orjson
import requests
from django.conf import settings
from rest_framework.request import Request
from rest_framework.response import Response

from sentry.api.api_owners import ApiOwner
from sentry.api.api_publish_status import ApiPublishStatus
from sentry.api.base import region_silo_endpoint
from sentry.api.bases.organization import OrganizationEndpoint, OrganizationPermission
from sentry.models.organization import Organization
from sentry.seer.explorer.client_utils import fetch_run_status, has_seer_explorer_access_with_detail
from sentry.seer.signed_seer_api import sign_with_seer_secret

logger = logging.getLogger(__name__)


class OrganizationSeerExplorerUpdatePermission(OrganizationPermission):
    scope_map = {
        "POST": ["org:read"],
    }


@region_silo_endpoint
class OrganizationSeerExplorerUpdateEndpoint(OrganizationEndpoint):
    publish_status = {
        "POST": ApiPublishStatus.EXPERIMENTAL,
    }
    owner = ApiOwner.ML_AI
    permission_classes = (OrganizationSeerExplorerUpdatePermission,)

    def post(self, request: Request, organization: Organization, run_id: int) -> Response:
        """
        Send an update event to explorer for a given run.
        """
        has_access, error = has_seer_explorer_access_with_detail(organization, request.user)
        if not has_access:
            return Response({"detail": error}, status=403)

        if not request.data:
            return Response(status=400, data={"error": "Need a body with a payload"})

        # The run id comes from the URL, so it must be checked against the organization the
        # request is scoped to before we relay anything to Seer.
        try:
            fetch_run_status(int(run_id), organization)
        except (ValueError, TypeError):
            return Response(status=404, data={"error": "Run not found"})

        path = "/v1/automation/explorer/update"

        body = orjson.dumps(
            {
                **request.data,
                "run_id": int(run_id),
                "organization_id": organization.id,
            },
            option=orjson.OPT_NON_STR_KEYS,
        )

        response = requests.post(
            f"{settings.SEER_AUTOFIX_URL}{path}",
            data=body,
            headers={
                "content-type": "application/json;charset=utf-8",
                **sign_with_seer_secret(body),
            },
        )

        response.raise_for_status()

        return Response(status=202, data=response.json())
