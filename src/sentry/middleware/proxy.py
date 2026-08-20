from typing import Any

from django.conf import settings
from django.core.exceptions import MiddlewareNotUsed
from django.http.request import HttpRequest
from django.utils.deprecation import MiddlewareMixin

from sentry.utils.http import PEER_ADDR_META_KEY, remove_port_number


class SetRemoteAddrFromForwardedFor(MiddlewareMixin):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        if not getattr(settings, "SENTRY_USE_X_FORWARDED_FOR", True):
            raise MiddlewareNotUsed
        super().__init__(*args, **kwargs)

    def _remove_port_number(self, ip_address: str) -> str:
        return remove_port_number(ip_address)

    def process_request(self, request: HttpRequest) -> None:
        if "REMOTE_ADDR" in request.META:
            request.META[PEER_ADDR_META_KEY] = request.META["REMOTE_ADDR"]

        try:
            real_ip = request.META["HTTP_X_FORWARDED_FOR"]
        except KeyError:
            pass
        else:
            # HTTP_X_FORWARDED_FOR can be a comma-separated list of IPs.
            # Take just the first one.
            real_ip = real_ip.split(",")[0].strip()
            real_ip = self._remove_port_number(real_ip)
            request.META["REMOTE_ADDR"] = real_ip
