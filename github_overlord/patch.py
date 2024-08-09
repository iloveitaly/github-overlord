from github.Notification import Notification


def mark_as_done(self) -> None:
    """
    :calls: `PATCH /notifications/threads/{id} <https://docs.github.com/en/rest/activity/notifications?apiVersion=2022-11-28#mark-a-thread-as-done>`_
    """
    headers, data = self._requester.requestJsonAndCheck(
        "DELETE",
        self.url,
    )


Notification.mark_as_done = mark_as_done
