from django.conf import settings
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response

from sentry.api.api_owners import ApiOwner
from sentry.api.api_publish_status import ApiPublishStatus
from sentry.api.base import Endpoint, all_silo_endpoint
from sentry.api.permissions import SuperuserPermission
from sentry.conf.server import SENTRY_EARLY_FEATURES
from sentry.runner.settings import configure, discover_configs


@all_silo_endpoint
class InternalFeatureFlagsEndpoint(Endpoint):
    permission_classes = (SuperuserPermission,)
    owner = ApiOwner.HYBRID_CLOUD
    publish_status = {
        "GET": ApiPublishStatus.PRIVATE,
        "PUT": ApiPublishStatus.PRIVATE,
    }

    def get(self, request: Request) -> Response:
        if not settings.SENTRY_SELF_HOSTED:
            return Response("You are not self-hosting Sentry.", status=403)

        result = {}
        for key in SENTRY_EARLY_FEATURES:
            result[key] = {
                "value": settings.SENTRY_FEATURES.get(key, False),
                "description": SENTRY_EARLY_FEATURES[key],
            }

        return Response(result)

    def put(self, request: Request) -> Response:
        if not settings.SENTRY_SELF_HOSTED:
            return Response("You are not self-hosting Sentry.", status=403)

        # sentry.conf.py is exec()'d on startup, so only normalized boolean literals
        # for known flag names may ever be written to it.
        boolean_field = serializers.BooleanField()
        updates: dict[str, bool] = {}
        for flag in request.data.keys():
            if not SENTRY_EARLY_FEATURES.get(flag, False):
                continue
            try:
                updates[flag] = boolean_field.run_validation(request.data.get(flag))
            except serializers.ValidationError:
                return Response(
                    {flag: "Feature flag values must be a boolean."},
                    status=400,
                )

        _, py, yml = discover_configs()
        # Open the file for reading and writing
        with open(py, "r+") as file:
            lines = file.readlines()
            for valid_flag, value in updates.items():
                match_found = False
                new_string = f"\nSENTRY_FEATURES[{valid_flag!r}]={value!r}\n"
                # Search for the string match and update lines
                for i, line in enumerate(lines):
                    if valid_flag in line:
                        match_found = True
                        lines[i] = new_string

                        break

                # If no match found, append a new line
                if not match_found:
                    lines.append(new_string)

            # Move the file pointer to the beginning and truncate the file
            file.seek(0)
            file.truncate()

            # Write modified lines back to the file
            file.writelines(lines)

        configure(None, py, yml)

        return Response(status=200)
