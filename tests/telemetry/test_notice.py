"""The first-run notice reaches the user once, on the first reply that can carry it -
never on `listen`'s, which is the user's own words."""

from fakes import FakeEngine, FakeMicLock, FakeQueue, FakeRecorder, FakeSpeaker, FakeTranscriber
from walkie.capture import Recording, State, TrackerSettings
from walkie.config import Settings
from walkie.cue import Cue
from walkie.server import Ears, create_server
from walkie.telemetry.notice import FOR_THE_MODEL, TEXT, Notice


def test_the_notice_is_handed_out_once_and_marked_shown_once():
    marked = []
    notice = Notice(pending=True, mark_shown=lambda: marked.append(1))
    first = notice.take()
    assert first is not None and first.startswith(FOR_THE_MODEL) and TEXT in first
    assert notice.take() is None
    assert marked == [1]


def test_a_notice_already_shown_is_never_handed_out():
    marked = []
    assert Notice(pending=False, mark_shown=lambda: marked.append(1)).take() is None
    assert marked == []


def test_a_notice_shown_out_of_band_since_startup_is_not_handed_out_again():
    """`/walkie:setup` may have printed it after this session started."""
    marked = []
    notice = Notice(pending=True, mark_shown=lambda: marked.append(1), still_due=lambda: False)
    assert notice.take() is None
    assert marked == []


def test_the_text_names_the_runnable_commands_and_never_the_content():
    for command in ("/walkie:telemetry off", "/walkie:telemetry local", "/walkie:stats"):
        assert command in TEXT
    flat = " ".join(TEXT.split())
    assert "never sends what you or the agent say, or any audio" in flat
    assert "stays in walkie's store on this machine" in flat


def served(notice: Notice, *, listening: bool = False) -> object:
    ears = (
        Ears(
            recorder=FakeRecorder(Recording(wav=b"RIFF", reason=State.DONE, has_speech=True)),
            transcriber=FakeTranscriber(text="run the tests", reachable=True),
            mic_lock=FakeMicLock(),
            speaker=FakeSpeaker(),
            limits=TrackerSettings(),
            cue=Cue(enabled=False),
        )
        if listening
        else None
    )
    return create_server(
        settings=Settings.from_env({}, platform="darwin"),
        engine=FakeEngine(),
        queue=FakeQueue(),
        supervisor=None,
        ears=ears,
        notice=notice,
    )


async def text_of(server, name: str, **arguments: object) -> str:
    return (await server.call_tool(name, arguments)).content[0].text


async def test_only_the_first_tool_reply_carries_it():
    server = served(Notice(pending=True, mark_shown=lambda: None))
    first = await text_of(server, "speech_status")
    second = await text_of(server, "speech_status")
    assert TEXT in first
    assert TEXT not in second


async def test_every_tool_but_listen_can_carry_it():
    for name, arguments in (
        ("speak", {"text": "hi"}),
        ("list_voices", {}),
        ("set_voice", {"voice": "Sofia"}),
        ("stop_speaking", {}),
        ("speech_status", {}),
    ):
        server = served(Notice(pending=True, mark_shown=lambda: None))
        assert TEXT in await text_of(server, name, **arguments), name


async def test_listen_never_carries_it_and_leaves_it_for_the_next_reply():
    marked = []
    server = served(Notice(pending=True, mark_shown=lambda: marked.append(1)), listening=True)
    assert await text_of(server, "listen") == "run the tests"
    assert marked == []
    assert TEXT in await text_of(server, "speech_status")
    assert marked == [1]
