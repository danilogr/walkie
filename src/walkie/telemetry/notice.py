"""The first-run notice walkie shows before it collects or sends anything. Whether it
is owed is speak-core's `telemetry.notice`; the words, and where they appear, are
walkie's: appended to the first reply of a session from any tool but `listen`, and
printed by `/walkie:setup`. A tool reply reaches the model, not the user, so it carries
an instruction to show the notice word for word. `listen`'s reply is the user's own
words and is never mixed with anything else, and `/walkie:talk` never shows it: its
output is read as the user's prompt."""

from collections.abc import Callable

TELEMETRY_URL = "https://github.com/danilogr/walkie/blob/main/TELEMETRY.md"

TEXT = f"""walkie collects anonymous usage data: which features you use, how long speech
and listening take on your machine, and why they fail (never what you or the agent
say, and never any audio).

  /walkie:telemetry off     collect nothing; send only an anonymous install count
  /walkie:telemetry local   keep the data; send only an anonymous install count
  /walkie:stats             see your own

Details: {TELEMETRY_URL}"""

FOR_THE_MODEL = "walkie's one-time telemetry notice. Show it to the user word for word, once:"


class Notice:
    """The notice for one session: handed out at most once, and marked shown when it is."""

    def __init__(
        self,
        *,
        pending: bool,
        mark_shown: Callable[[], object],
        still_due: Callable[[], bool] = lambda: True,
    ) -> None:
        self._pending = pending
        self._mark_shown = mark_shown
        # Asked again at hand-out: `/walkie:setup` may have shown it since startup.
        self._still_due = still_due

    def take(self) -> str | None:
        if not self._pending:
            return None
        self._pending = False
        if not self._still_due():
            return None
        self._mark_shown()
        return f"{FOR_THE_MODEL}\n\n{TEXT}"
