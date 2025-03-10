from pprint import pformat
from threading import Timer
import html
import os
import string

from bokeh.io import output_file, show
from bokeh.layouts import layout, row
from bokeh.models.widgets import Div
from loguru import logger
from tqdm import tqdm

from openadapt.crud import (
    get_latest_recording,
)
from openadapt.events import (
    get_events,
)
from openadapt.utils import (
    configure_logging,
    display_event,
    evenly_spaced,
    image2utf8,
    EMPTY,
    row2dict,
    rows2dicts,
)

from openadapt import config

SCRUB = config.SCRUB_ENABLED
if SCRUB:
    from openadapt import scrub

LOG_LEVEL = "INFO"
MAX_EVENTS = None
MAX_TABLE_CHILDREN = 5
MAX_TABLE_STR_LEN = 1024
PROCESS_EVENTS = True
IMG_WIDTH_PCT = 60
CSS = string.Template(
    """
    table {
        outline: 1px solid black;
    }
    table th {
        vertical-align: top;
    }
    .screenshot img {
        display: none;
        width: ${IMG_WIDTH_PCT}vw;
    }
    .screenshot img:nth-child(1) {
        display: block;
    }

    .screenshot:hover img:nth-child(1) {
        display: none;
    }
    .screenshot:hover img:nth-child(2) {
        display: block;
    }
    .screenshot:hover img:nth-child(3) {
        display: none;
    }

    .screenshot:active img:nth-child(1) {
        display: none;
    }
    .screenshot:active img:nth-child(2) {
        display: none;
    }
    .screenshot:active img:nth-child(3) {
        display: block;
    }
"""
).substitute(
    IMG_WIDTH_PCT=IMG_WIDTH_PCT,
)


def recursive_len(lst, key):
    try:
        _len = len(lst)
    except TypeError:
        return 0
    for obj in lst:
        try:
            _len += recursive_len(obj.get(key), key)
        except AttributeError:
            continue
    return _len


def format_key(key, value):
    if isinstance(value, list):
        return f"{key} ({len(value)}; {recursive_len(value, key)})"
    else:
        return key


def indicate_missing(some, every, indicator):
    rval = []
    some_idx = 0
    every_idx = 0
    while some_idx < len(some):
        skipped = False
        while some[some_idx] != every[every_idx]:
            every_idx += 1
            skipped = True
        if skipped:
            rval.append(indicator)
        rval.append(some[some_idx])
        some_idx += 1
        every_idx += 1
    return rval


def dict2html(obj, max_children=MAX_TABLE_CHILDREN, max_len=MAX_TABLE_STR_LEN):
    if isinstance(obj, list):
        children = [dict2html(value, max_children) for value in obj]
        if max_children is not None and len(children) > max_children:
            all_children = children
            children = evenly_spaced(children, max_children)
            children = indicate_missing(children, all_children, "...")
        html_str = "\n".join(children)
    elif isinstance(obj, dict):
        rows_html = "\n".join(
            [
                f"""
                <tr>
                    <th>{format_key(key, value)}</th>
                    <td>{dict2html(value, max_children)}</td>
                </tr>
            """
                for key, value in obj.items()
                if value not in EMPTY
            ]
        )
        html_str = f"<table>{rows_html}</table>"
    else:
        html_str = html.escape(str(obj))
        if len(html_str) > max_len:
            n = max_len // 2
            head = html_str[:n]
            tail = html_str[-n:]
            snipped = html_str[n:-n]
            middle = f"<br/>...<i>(snipped {len(snipped):,})...</i><br/>"
            html_str = head + middle + tail
    return html_str

@logger.catch
def main():
    configure_logging(logger, LOG_LEVEL)

    recording = get_latest_recording()
    if SCRUB:
        scrub.scrub_text(recording.task_description)
    logger.debug(f"{recording=}")

    meta = {}
    action_events = get_events(recording, process=PROCESS_EVENTS, meta=meta)
    event_dicts = rows2dicts(action_events)

    if SCRUB:
        event_dicts = scrub.scrub_list_dicts(event_dicts)
    logger.info(f"event_dicts=\n{pformat(event_dicts)}")

    recording_dict = row2dict(recording)
    if SCRUB:
        recording_dict = scrub.scrub_dict(recording_dict)

    rows = [
        row(
            Div(
                text=f"<style>{CSS}</style>",
            ),
        ),
        row(
            Div(
                text=f"{dict2html(recording_dict)}",
            ),
        ),
        row(
            Div(
                text=f"{dict2html(meta)}",
                width_policy="max",
            ),
        ),
    ]
    logger.info(f"{len(action_events)=}")

    num_events = (
        min(MAX_EVENTS, len(action_events))
        if MAX_EVENTS is not None
        else len(action_events)
    )
    with tqdm(
            total=num_events,
            desc="Preparing HTML",
            unit="event",
            colour="green",
            dynamic_ncols=True,
        ) as progress:
        for idx, action_event in enumerate(action_events):
            if idx == MAX_EVENTS:
                break
            image = display_event(action_event)
            diff = display_event(action_event, diff=True)
            mask = action_event.screenshot.diff_mask

            if SCRUB:
                image = scrub.scrub_image(image)
                diff = scrub.scrub_image(diff)
                mask = scrub.scrub_image(mask)

            image_utf8 = image2utf8(image)
            diff_utf8 = image2utf8(diff)
            mask_utf8 = image2utf8(mask)
            width, height = image.size

            action_event_dict = row2dict(action_event)
            window_event_dict = row2dict(action_event.window_event)

            if SCRUB:
                action_event_dict = scrub.scrub_dict(action_event_dict)
                window_event_dict = scrub.scrub_dict(window_event_dict)

            rows.append(
                [
                    row(
                        Div(
                            text=f"""
                            <div class="screenshot">
                                <img
                                    src="{image_utf8}"
                                    style="
                                        aspect-ratio: {width}/{height};
                                    "
                                >
                                <img
                                    src="{diff_utf8}"
                                    style="
                                        aspect-ratio: {width}/{height};
                                    "
                                >
                                <img
                                    src="{mask_utf8}"
                                    style="
                                        aspect-ratio: {width}/{height};
                                    "
                                >
                            </div>
                            <table>
                                {dict2html(window_event_dict , None)}
                            </table>
                        """,
                        ),
                        Div(
                            text=f"""
                            <table>
                                {dict2html(action_event_dict)}
                            </table>
                        """
                        ),
                    ),
                ]
            )

            progress.update()

        progress.close()

    title = f"recording-{recording.id}"
    fname_out = f"recording-{recording.id}.html"
    logger.info(f"{fname_out=}")
    output_file(fname_out, title=title)

    result = show(
        layout(
            rows,
        )
    )

    def cleanup():
        os.remove(fname_out)
        removed = not os.path.exists(fname_out)
        logger.info(f"{removed=}")

    Timer(1, cleanup).start()


if __name__ == "__main__":
    main()
