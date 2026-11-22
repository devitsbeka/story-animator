#!/usr/bin/env python3
"""
MARKS: the one place where the sentinel yacht's interaction points live (spec yacht-local coords: +x = the hero's
left when he faces the bow, +y up, +z = bow). Shared by the episode builders (actor marks, camera re-aims) and the
yacht / set agents: if the yacht is rebuilt, update the numbers HERE and re-run the builders.

Current yacht (studio/public/assets/props/yacht.glb): the cockpit bench is 'upholstery_dark_38', spanning
x -1.2..1.2, z -5.55..-4.85, top at y 1.83; cockpit deck at y 1.42 (seat height 0.41 m). No backrest / padded
surface behind it (open deck to the transom), so 'sit_deck_relaxed' has no 'backrest' anchor on this boat.
"""

DECK_Y = 1.42

BENCH = {"x": (-1.2, 1.2), "z": (-5.55, -4.85), "top": 1.83, "deck": DECK_Y,
         "source": "yacht.glb upholstery_dark_38"}

# where the butt meets the seat: 0.16 m behind the bench's front edge (thighs on the cushion, knees just past it)
SEAT_SETBACK = 0.16
# the actor's mark (his feet) for sitting on the bench: in front of the edge, shins ~vertical for Jay at 1.8 m (thigh 0.29 m, shin 0.27 m)
FEET_FROM_EDGE = 0.10


def bench_seat(x):
    """spec point on the bench top under the butt, for a hero sitting at lateral position x."""
    return [round(x, 3), BENCH["top"], round(BENCH["z"][1] - SEAT_SETBACK, 3)]


def bench_mark(x):
    """actor local + rotY for sitting on the bench facing the bow (stand there, then 'sit_bench')."""
    return {"local": [round(x, 3), DECK_Y, round(BENCH["z"][1] + FEET_FROM_EDGE, 3)], "rotY": 0.0}


# the sit beat of act C (C21 sits down, C22 stays seated): the port half of the bench, clear of the helm (x 0.1..1.0)
SIT_X = -0.55
SIT_MARK = bench_mark(SIT_X)
SIT_ANCHORS = {"bench_seat": {"p": bench_seat(SIT_X), "space": "yacht"}}
