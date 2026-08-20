from functools import cached_property

from sentry.testutils.cases import TestCase
from sentry.testutils.helpers.datetime import before_now
from sentry.utils import json


class GroupEventJsonTest(TestCase):
    @cached_property
    def path(self) -> str:
        return f"/organizations/{self.organization.slug}/issues/{self.event.group_id}/events/{self.event.event_id}/json/"

    def test_does_render(self) -> None:
        self.login_as(self.user)
        min_ago = before_now(minutes=1).isoformat()
        self.event = self.store_event(
            data={"fingerprint": ["group1"], "timestamp": min_ago}, project_id=self.project.id
        )
        resp = self.client.get(self.path)
        assert resp.status_code == 200
        assert resp["Content-Type"] == "application/json"
        data = json.loads(resp.content.decode("utf-8"))
        assert data["event_id"] == self.event.event_id

    def test_group_from_another_organization(self) -> None:
        other_org = self.create_organization()
        other_project = self.create_project(organization=other_org)
        other_event = self.store_event(
            data={"fingerprint": ["group1"], "timestamp": before_now(minutes=1).isoformat()},
            project_id=other_project.id,
        )

        self.login_as(self.user)
        resp = self.client.get(
            f"/organizations/{self.organization.slug}/issues/{other_event.group_id}/events/{other_event.event_id}/json/"
        )
        assert resp.status_code == 404

        resp = self.client.get(
            f"/organizations/{self.organization.slug}/issues/{other_event.group_id}/events/latest/json/"
        )
        assert resp.status_code == 404

    def test_group_from_inaccessible_team(self) -> None:
        team = self.create_team(organization=self.organization)
        project = self.create_project(organization=self.organization, teams=[team])
        event = self.store_event(
            data={"fingerprint": ["group1"], "timestamp": before_now(minutes=1).isoformat()},
            project_id=project.id,
        )
        member = self.create_user()
        self.create_member(organization=self.organization, user=member, role="member", teams=[])

        self.login_as(member)
        resp = self.client.get(
            f"/organizations/{self.organization.slug}/issues/{event.group_id}/events/latest/json/"
        )
        assert resp.status_code == 404
