"""Random inspiration for the proposer: these models don't accept temperature, so variety comes from the prompt."""

import random

SETTINGS = [
    "a lighthouse keeper's logbook", "a night market full of food stalls", "a chess club tournament",
    "a bakery's weekend rush", "a train station departure board", "a robot vacuum on a tiled floor",
    "a treasure map drawn on a grid", "a pirate crew splitting loot", "a mountain relay race",
    "a library reshuffling its shelves", "a garden of flowerbeds and paths", "a carnival ring-toss booth",
    "a spaceship docking queue", "a beehive's honeycomb", "a board game night with friends",
    "a city of one-way streets", "an orchestra seating chart", "a dragon hoarding coins",
    "a snowflake-shaped cookie cutter", "a museum with security cameras", "a frog hopping between lily pads",
    "a pizza cut by straight slices", "a card magician's routine", "a sailing regatta around buoys",
    "a stack of pancakes being flipped", "a village with truth-tellers and liars", "a vending machine's coins",
    "a knight touring a small board", "a dice game at a medieval inn", "a paper-folding contest",
    "an elevator in a very tall building", "a school timetable", "a set of dominoes", "a clock tower's gears",
]

TWISTS = [
    "the answer is surprisingly small", "a hidden symmetry makes it tractable", "it involves a process that stops",
    "the obvious first guess is wrong", "it is about the best possible strategy", "it lives on a grid",
    "it involves a circle or a sphere", "it features an expected waiting time", "a parity argument is key",
    "it counts paths or routes", "it involves splitting something fairly", "it involves a repeated operation",
    "it asks for the largest or smallest possible value", "it combines two simple rules into a surprise",
]


def random_seed(rng: random.Random | None = None) -> str:
    rng = rng or random
    return f"setting: {rng.choice(SETTINGS)}; twist: {rng.choice(TWISTS)}"
