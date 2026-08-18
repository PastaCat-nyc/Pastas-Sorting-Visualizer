"""Algorithm Visualizer - pygame app.

Sort/race/benchmark logic lives in sorting_algorithms.py (no pygame
dependency, independently unit tested by test_algorithms.py). This file
only handles rendering, audio, input, and the two small pieces of
mutable UI state (AppState for the main view, RaceState for race mode).

Settings (algorithm, shuffle mode, bar count, speed, mute) persist
between runs in visualizer_settings.json, saved next to this script.
"""

import json
import math
import os
import time
from array import array
from dataclasses import dataclass, field

import pygame

from sorting_algorithms import (
    ALGORITHM_COMPLEXITY,
    ALGORITHMS,
    GRAPH_HEIGHT,
    MAX_BARS,
    MIN_BARS,
    RaceSorter,
    SHUFFLE_MODES,
    SORT_GENERATORS,
    cycle_algorithm,
    cycle_shuffle,
    generate_values,
    new_stats,
    run_benchmark,
)

pygame.init()
pygame.mixer.init()

# ============================================================
# WINDOW
# ============================================================

WIDTH = 1000
HEIGHT = 840
PANEL_HEIGHT = HEIGHT - GRAPH_HEIGHT

screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("Algorithm Visualizer")

clock = pygame.time.Clock()

# ============================================================
# COLORS
# ============================================================

BACKGROUND = (25, 25, 25)
PANEL_COLOR = (40, 40, 40)

BUTTON_COLOR = (65, 65, 65)
BUTTON_HOVER = (85, 85, 85)

TEXT_COLOR = (235, 235, 235)
WHITE = (255, 255, 255)
RED = (255, 80, 80)
GREEN = (100, 220, 120)
GRAY = (160, 160, 160)

# ============================================================
# FONTS
# ============================================================

small_font = pygame.font.SysFont("Arial", 15)
normal_font = pygame.font.SysFont("Arial", 18)
title_font = pygame.font.SysFont("Arial", 25, bold=True)
big_font = pygame.font.SysFont("Arial", 34, bold=True)

# ============================================================
# SETTINGS PERSISTENCE
# ============================================================

SETTINGS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "visualizer_settings.json")


def load_settings(state):
    if not os.path.exists(SETTINGS_PATH):
        return

    try:
        with open(SETTINGS_PATH, "r") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return

    global sound_enabled

    state.algorithm_index = int(data.get("algorithm_index", state.algorithm_index)) % len(ALGORITHMS)
    state.shuffle_index = int(data.get("shuffle_index", state.shuffle_index)) % len(SHUFFLE_MODES)
    state.num_bars = max(MIN_BARS, min(MAX_BARS, int(data.get("num_bars", state.num_bars))))
    state.sort_delay = max(0, min(50, int(data.get("sort_delay", state.sort_delay))))
    sound_enabled = bool(data.get("sound_enabled", sound_enabled))

    state.values = generate_values(state.shuffle_mode, state.num_bars)


def save_settings(state):
    data = {
        "algorithm_index": state.algorithm_index,
        "shuffle_index": state.shuffle_index,
        "num_bars": state.num_bars,
        "sort_delay": state.sort_delay,
        "sound_enabled": sound_enabled,
    }
    try:
        with open(SETTINGS_PATH, "w") as f:
            json.dump(data, f, indent=2)
    except OSError:
        pass


# ============================================================
# SOUND
# ============================================================
# create_beep() builds a waveform sample-by-sample in pure Python, which
# is too slow to call on every comparison. Cache Sound objects by
# (rounded) frequency so repeated pitches are reused instead of
# regenerated from scratch.

NORMAL_SOUND_VOLUME = 0.12
NORMAL_MIN_FREQUENCY = 140
NORMAL_MAX_FREQUENCY = 550

FINISH_MIN_FREQUENCY = 100
FINISH_MAX_FREQUENCY = 700

RACE_SOUND_VOLUME = 0.055
RACE_MIN_FREQUENCY = 350
RACE_MAX_FREQUENCY = 1100

sound_enabled = True
_beep_cache = {}


def toggle_sound():
    global sound_enabled
    sound_enabled = not sound_enabled


def create_beep(frequency, duration=0.025, volume=0.15):
    sample_rate = 44100
    num_samples = int(sample_rate * duration)
    fade_samples = max(1, num_samples * 0.1)

    sound_array = array("h")

    for i in range(num_samples):
        wave = math.sin(2 * math.pi * frequency * i / sample_rate)
        fade_in = min(1.0, i / fade_samples)
        fade_out = min(1.0, (num_samples - i) / fade_samples)
        fade = min(fade_in, fade_out)

        sample = int(wave * 10000 * volume * fade)
        sound_array.append(sample)
        sound_array.append(sample)

    return pygame.mixer.Sound(buffer=sound_array.tobytes())


def get_beep(frequency, duration, volume, bucket=4):
    # Round the frequency so nearby pitches share a cached Sound instead
    # of each triggering a fresh waveform generation.
    frequency = int(round(frequency / bucket) * bucket)
    key = (frequency, duration, volume)

    sound = _beep_cache.get(key)
    if sound is None:
        sound = create_beep(frequency, duration, volume)
        _beep_cache[key] = sound

    return sound


def play_sort_sound(value):
    if not sound_enabled:
        return
    ratio = max(0, min(1, value / GRAPH_HEIGHT))
    frequency = NORMAL_MIN_FREQUENCY + ratio * (NORMAL_MAX_FREQUENCY - NORMAL_MIN_FREQUENCY)
    get_beep(frequency, 0.018, NORMAL_SOUND_VOLUME).play()


def play_race_sound(value, side):
    if not sound_enabled:
        return
    ratio = max(0, min(1, value / GRAPH_HEIGHT))
    frequency = RACE_MIN_FREQUENCY + ratio * (RACE_MAX_FREQUENCY - RACE_MIN_FREQUENCY)
    frequency *= 0.90 if side == 0 else 1.10
    get_beep(frequency, 0.014, RACE_SOUND_VOLUME).play()


def play_finish_sound(value):
    if not sound_enabled:
        return
    ratio = max(0, min(1, value / GRAPH_HEIGHT))
    frequency = FINISH_MIN_FREQUENCY + ratio * (FINISH_MAX_FREQUENCY - FINISH_MIN_FREQUENCY)
    get_beep(frequency, 0.035, 0.11).play()


# ============================================================
# APP STATE
# ============================================================
# Bundling the main view's mutable state into one object removes the
# ~15 "global X" declarations a flat-globals version would need.
# Functions take `state` as a parameter and mutate its attributes
# directly.

@dataclass
class AppState:
    num_bars: int = 80
    algorithm_index: int = 0
    shuffle_index: int = 0
    sort_delay: int = 20  # 50 = slow, 0 = maximum speed
    sorting: bool = False
    paused: bool = False
    step_requested: bool = False
    stop_requested: bool = False
    status: str = "Ready"
    comparisons: int = 0
    swaps: int = 0
    writes: int = 0
    sort_start_time: float = 0.0
    sort_time: float = 0.0
    dragging_speed: bool = False
    dragging_bar_slider: bool = False
    values: list = field(default_factory=list)

    def __post_init__(self):
        if not self.values:
            self.values = generate_values(self.shuffle_mode, self.num_bars)

    @property
    def algorithm(self):
        return ALGORITHMS[self.algorithm_index]

    @property
    def shuffle_mode(self):
        return SHUFFLE_MODES[self.shuffle_index]

    def reset_stats(self):
        self.comparisons = 0
        self.swaps = 0
        self.writes = 0
        self.sort_time = 0.0

    def reshuffle(self):
        self.values = generate_values(self.shuffle_mode, self.num_bars)
        self.status = "Ready"
        self.reset_stats()


@dataclass
class RaceState:
    algorithm_1: str = "Bubble Sort"
    algorithm_2: str = "Quick Sort"
    shuffle_mode: str = "Random"
    bar_count: int = 80
    speed: int = 15  # 0 = maximum speed, 50 = minimum speed
    dragging_bars: bool = False
    dragging_speed: bool = False
    paused: bool = False
    step_requested: bool = False


state = AppState()
race_state = RaceState()
load_settings(state)

# ============================================================
# BAR COLOR / DRAWING
# ============================================================

def get_bar_color(value):
    ratio = max(0, min(1, (value - 20) / (GRAPH_HEIGHT - 50)))
    return (255, int(255 * (1 - ratio)), 0)


def draw_bars(data, compare_indices=None, x_offset=0, graph_width=WIDTH):
    if not data:
        return

    compare_indices = compare_indices or []
    current_width = graph_width / len(data)

    for i, value in enumerate(data):
        x = int(x_offset + i * current_width)
        y = GRAPH_HEIGHT - value
        color = WHITE if i in compare_indices else get_bar_color(value)
        rect = (x, y, max(1, int(current_width - 2)), value)
        pygame.draw.rect(screen, color, rect)


def draw_button(rect, text, special_color=None):
    mouse = pygame.mouse.get_pos()

    if special_color is not None:
        color = special_color
    elif rect.collidepoint(mouse):
        color = BUTTON_HOVER
    else:
        color = BUTTON_COLOR

    pygame.draw.rect(screen, color, rect, border_radius=6)
    pygame.draw.rect(screen, (100, 100, 100), rect, 2, border_radius=6)

    text_surface = small_font.render(text, True, TEXT_COLOR)
    screen.blit(text_surface, text_surface.get_rect(center=rect.center))


# ============================================================
# SLIDERS / BUTTON ROW LAYOUT
# ============================================================
# Rects are static, so build them once instead of allocating a new
# pygame.Rect every frame. update_* functions share one ratio helper.

BUTTON_ROW_Y = GRAPH_HEIGHT + 120

START_BUTTON = pygame.Rect(20, BUTTON_ROW_Y, 110, 38)
ALGORITHM_BUTTON = pygame.Rect(140, BUTTON_ROW_Y, 170, 38)
SHUFFLE_BUTTON = pygame.Rect(320, BUTTON_ROW_Y, 170, 38)
RACE_BUTTON = pygame.Rect(800, BUTTON_ROW_Y, 160, 38)

SPEED_SLIDER = pygame.Rect(600, BUTTON_ROW_Y, 180, 8)
BAR_SLIDER = pygame.Rect(600, BUTTON_ROW_Y + 35, 180, 8)

RACE_BAR_SLIDER = pygame.Rect(250, 380, 500, 8)
RACE_SPEED_SLIDER = pygame.Rect(250, 460, 500, 8)


def slider_ratio(rect, mouse_x):
    return max(0, min(1, (mouse_x - rect.x) / rect.width))


def update_speed(state, mouse_x):
    state.sort_delay = int(50 - slider_ratio(SPEED_SLIDER, mouse_x) * 50)


def update_bar_count(state, mouse_x):
    state.num_bars = int(MIN_BARS + slider_ratio(BAR_SLIDER, mouse_x) * (MAX_BARS - MIN_BARS))
    state.values = generate_values(state.shuffle_mode, state.num_bars)


def update_race_bar_count(race_state, mouse_x):
    race_state.bar_count = int(
        MIN_BARS + slider_ratio(RACE_BAR_SLIDER, mouse_x) * (MAX_BARS - MIN_BARS)
    )


def update_race_speed(race_state, mouse_x):
    race_state.speed = int(slider_ratio(RACE_SPEED_SLIDER, mouse_x) * 50)


# ============================================================
# MAIN PANEL
# ============================================================

def draw_panel(state):
    pygame.draw.rect(screen, PANEL_COLOR, (0, GRAPH_HEIGHT, WIDTH, PANEL_HEIGHT))

    title = title_font.render("Algorithm Visualizer", True, TEXT_COLOR)
    screen.blit(title, (20, GRAPH_HEIGHT + 10))

    sound_label = "ON" if sound_enabled else "MUTED"
    status_text = small_font.render(
        f"Algorithm: {state.algorithm}    Status: {state.status}    Sound: {sound_label}",
        True,
        TEXT_COLOR,
    )
    screen.blit(status_text, (20, GRAPH_HEIGHT + 38))

    stats = small_font.render(
        f"Comparisons: {state.comparisons}    Swaps: {state.swaps}    "
        f"Writes: {state.writes}    Time: {state.sort_time:.2f}s",
        True,
        GRAY,
    )
    screen.blit(stats, (20, GRAPH_HEIGHT + 60))

    complexity = ALGORITHM_COMPLEXITY[state.algorithm]
    complexity_text = small_font.render(
        f"Best: {complexity['best']}    Avg: {complexity['average']}    "
        f"Worst: {complexity['worst']}    Space: {complexity['space']}",
        True,
        GRAY,
    )
    screen.blit(complexity_text, (20, GRAPH_HEIGHT + 82))

    if state.sorting:
        draw_button(START_BUTTON, "RESUME" if state.paused else "STOP", RED)
    else:
        draw_button(START_BUTTON, "START")

    draw_button(ALGORITHM_BUTTON, state.algorithm.upper())
    draw_button(SHUFFLE_BUTTON, state.shuffle_mode.upper())

    speed_text = small_font.render("Speed", True, TEXT_COLOR)
    screen.blit(speed_text, (520, SPEED_SLIDER.y - 6))

    pygame.draw.rect(screen, (80, 80, 80), SPEED_SLIDER, border_radius=4)
    speed_ratio = (50 - state.sort_delay) / 50
    speed_x = int(SPEED_SLIDER.x + speed_ratio * SPEED_SLIDER.width)
    pygame.draw.circle(screen, WHITE, (speed_x, SPEED_SLIDER.centery), 8)

    bars_text = small_font.render(f"Bars: {state.num_bars}", True, TEXT_COLOR)
    screen.blit(bars_text, (520, BAR_SLIDER.y - 6))

    pygame.draw.rect(screen, (80, 80, 80), BAR_SLIDER, border_radius=4)
    bar_ratio = (state.num_bars - MIN_BARS) / (MAX_BARS - MIN_BARS)
    bar_x = int(BAR_SLIDER.x + bar_ratio * BAR_SLIDER.width)
    pygame.draw.circle(screen, WHITE, (bar_x, BAR_SLIDER.centery), 8)

    draw_button(RACE_BUTTON, "RACE MODE")

    controls_1 = small_font.render(
        "SPACE = Start    R = Shuffle    TAB = Algorithm    ESC = Stop", True, GRAY
    )
    screen.blit(controls_1, (20, GRAPH_HEIGHT + 175))

    controls_2 = small_font.render(
        "P = Pause    RIGHT = Step    M = Mute    B = Benchmark", True, GRAY
    )
    screen.blit(controls_2, (20, GRAPH_HEIGHT + 197))

    return START_BUTTON, ALGORITHM_BUTTON, SHUFFLE_BUTTON, RACE_BUTTON


# ============================================================
# SORT EVENT PROCESSING / DRAWING / DELAY
# ============================================================

def process_sort_events(state):
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            state.stop_requested = True
            return False

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                state.stop_requested = True
            elif event.key == pygame.K_p:
                state.paused = not state.paused
            elif event.key == pygame.K_RIGHT:
                if state.paused:
                    state.step_requested = True
            elif event.key == pygame.K_m:
                toggle_sound()

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if START_BUTTON.collidepoint(event.pos):
                state.stop_requested = True

    return not state.stop_requested


def draw_everything(state, compare_indices=None):
    screen.fill(BACKGROUND)
    draw_bars(state.values, compare_indices)
    draw_panel(state)
    pygame.display.flip()


def sorting_delay(state):
    if state.sort_delay <= 0:
        return process_sort_events(state)

    start = pygame.time.get_ticks()
    while pygame.time.get_ticks() - start < state.sort_delay:
        if not process_sort_events(state):
            return False
        clock.tick(240)

    return True


def wait_while_paused(state, highlight):
    """Freeze the sort in place while `state.paused` is set, still
    processing events (so stop/mute/step/resume keep working) and
    redrawing the current frame with a "Paused" status.

    Returns False if the user quit/stopped. Returns True once the sort
    should proceed - either because the user resumed (state.paused is
    now False) or because a single step was requested (state.paused is
    still True, but the caller should advance the generator exactly
    once and then come back here)."""

    while state.paused:
        if not process_sort_events(state):
            return False

        if state.step_requested:
            state.step_requested = False
            return True

        draw_everything(state, highlight)
        clock.tick(30)

    return True


# ============================================================
# FINISH ANIMATION
# ============================================================

def finish_animation(state):
    state.status = "Complete"

    for index in range(len(state.values)):
        if not process_sort_events(state):
            return False

        draw_everything(state, [index])
        play_finish_sound(state.values[index])
        pygame.time.delay(6)

    return True


# ============================================================
# RUN NORMAL SORT
# ============================================================

def run_sort(state):
    if state.sorting:
        return

    state.sorting = True
    state.stop_requested = False
    state.paused = False
    state.step_requested = False
    state.status = "Sorting..."
    state.reset_stats()

    stats = new_stats()
    state.sort_start_time = time.perf_counter()
    generator = SORT_GENERATORS[state.algorithm](state.values, stats)

    success = True
    highlight = []

    while True:
        if state.paused:
            state.status = "Paused"
            if not wait_while_paused(state, highlight):
                success = False
                break
            state.status = "Sorting..."

        try:
            highlight = next(generator)
        except StopIteration:
            break

        state.comparisons = stats["comparisons"]
        state.swaps = stats["swaps"]
        state.writes = stats["writes"]

        if not process_sort_events(state):
            success = False
            break

        draw_everything(state, highlight)

        if highlight:
            play_sort_sound(sum(state.values[i] for i in highlight) / len(highlight))

        if not sorting_delay(state):
            success = False
            break

    state.comparisons = stats["comparisons"]
    state.swaps = stats["swaps"]
    state.writes = stats["writes"]
    state.sort_time = time.perf_counter() - state.sort_start_time

    if success and not state.stop_requested:
        finish_animation(state)
    else:
        state.status = "Stopped"

    state.sorting = False
    state.stop_requested = False
    state.paused = False
    state.step_requested = False


# ============================================================
# BENCHMARK SCREEN
# ============================================================

def benchmark_screen(state):
    results = run_benchmark(state.shuffle_mode, state.num_bars)

    columns = [
        ("Algorithm", 60),
        ("Comparisons", 330),
        ("Swaps", 500),
        ("Writes", 630),
        ("Time (ms)", 780),
    ]

    waiting = True
    while waiting:
        screen.fill(BACKGROUND)

        title = big_font.render("BENCHMARK RESULTS", True, WHITE)
        screen.blit(title, (WIDTH // 2 - title.get_width() // 2, 30))

        subtitle = normal_font.render(
            f"{state.shuffle_mode} data, {state.num_bars} elements - fastest first",
            True,
            GRAY,
        )
        screen.blit(subtitle, (WIDTH // 2 - subtitle.get_width() // 2, 75))

        header_y = 140
        for label, x in columns:
            screen.blit(normal_font.render(label, True, GRAY), (x, header_y))

        pygame.draw.line(screen, (80, 80, 80), (40, header_y + 28), (WIDTH - 40, header_y + 28), 2)

        row_y = header_y + 45
        for i, result in enumerate(results):
            color = GREEN if i == 0 else TEXT_COLOR
            row_values = [
                result["algorithm"],
                f"{result['comparisons']:,}",
                f"{result['swaps']:,}",
                f"{result['writes']:,}",
                f"{result['time'] * 1000:.2f}",
            ]
            for (label, x), value in zip(columns, row_values):
                screen.blit(small_font.render(value, True, color), (x, row_y))
            row_y += 32

        hint = small_font.render("Click, ESC, or B to return", True, GRAY)
        screen.blit(hint, (WIDTH // 2 - hint.get_width() // 2, row_y + 25))

        pygame.display.flip()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                raise SystemExit

            if event.type == pygame.KEYDOWN and event.key in (pygame.K_ESCAPE, pygame.K_b):
                waiting = False

            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                waiting = False

        clock.tick(60)


# ============================================================
# RACE SETTINGS SCREEN
# ============================================================

def race_settings_screen(race_state):
    while True:
        screen.fill(BACKGROUND)

        title = big_font.render("RACE MODE", True, WHITE)
        screen.blit(title, (WIDTH // 2 - title.get_width() // 2, 30))

        subtitle = normal_font.render("Customize your race", True, GRAY)
        screen.blit(subtitle, (WIDTH // 2 - subtitle.get_width() // 2, 75))

        a1_button = pygame.Rect(250, 130, 500, 50)
        draw_button(a1_button, f"ALGORITHM 1: {race_state.algorithm_1}")

        a2_button = pygame.Rect(250, 200, 500, 50)
        draw_button(a2_button, f"ALGORITHM 2: {race_state.algorithm_2}")

        shuffle_button = pygame.Rect(250, 270, 500, 50)
        draw_button(shuffle_button, f"DATA: {race_state.shuffle_mode}")

        bars_label = normal_font.render(f"BAR COUNT: {race_state.bar_count}", True, TEXT_COLOR)
        screen.blit(bars_label, (250, 345))

        pygame.draw.rect(screen, (80, 80, 80), RACE_BAR_SLIDER, border_radius=4)
        bar_ratio = (race_state.bar_count - MIN_BARS) / (MAX_BARS - MIN_BARS)
        bar_x = int(RACE_BAR_SLIDER.x + bar_ratio * RACE_BAR_SLIDER.width)
        pygame.draw.circle(screen, WHITE, (bar_x, RACE_BAR_SLIDER.centery), 10)

        speed_label = normal_font.render(f"RACE SPEED: {race_state.speed}", True, TEXT_COLOR)
        screen.blit(speed_label, (250, 425))

        pygame.draw.rect(screen, (80, 80, 80), RACE_SPEED_SLIDER, border_radius=4)
        speed_ratio = race_state.speed / 50
        speed_x = int(RACE_SPEED_SLIDER.x + speed_ratio * RACE_SPEED_SLIDER.width)
        pygame.draw.circle(screen, WHITE, (speed_x, RACE_SPEED_SLIDER.centery), 10)

        start_button = pygame.Rect(250, 520, 240, 60)
        draw_button(start_button, "START RACE")

        back_button = pygame.Rect(510, 520, 240, 60)
        draw_button(back_button, "BACK")

        instructions = small_font.render(
            "Click algorithms to cycle - Drag sliders to customize", True, GRAY
        )
        screen.blit(instructions, (WIDTH // 2 - instructions.get_width() // 2, 620))

        instructions2 = small_font.render("ESC = Back", True, GRAY)
        screen.blit(instructions2, (WIDTH // 2 - instructions2.get_width() // 2, 650))

        pygame.display.flip()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                raise SystemExit

            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                race_state.dragging_bars = False
                race_state.dragging_speed = False
                return False

            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if a1_button.collidepoint(event.pos):
                    race_state.algorithm_1 = cycle_algorithm(race_state.algorithm_1)
                elif a2_button.collidepoint(event.pos):
                    race_state.algorithm_2 = cycle_algorithm(race_state.algorithm_2)
                elif shuffle_button.collidepoint(event.pos):
                    race_state.shuffle_mode = cycle_shuffle(race_state.shuffle_mode)
                elif RACE_BAR_SLIDER.collidepoint(event.pos):
                    race_state.dragging_bars = True
                    update_race_bar_count(race_state, event.pos[0])
                elif RACE_SPEED_SLIDER.collidepoint(event.pos):
                    race_state.dragging_speed = True
                    update_race_speed(race_state, event.pos[0])
                elif start_button.collidepoint(event.pos):
                    race_state.dragging_bars = False
                    race_state.dragging_speed = False
                    return True
                elif back_button.collidepoint(event.pos):
                    race_state.dragging_bars = False
                    race_state.dragging_speed = False
                    return False

            if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                race_state.dragging_bars = False
                race_state.dragging_speed = False

        if pygame.mouse.get_pressed()[0]:
            mouse_x = pygame.mouse.get_pos()[0]
            if race_state.dragging_bars:
                update_race_bar_count(race_state, mouse_x)
            if race_state.dragging_speed:
                update_race_speed(race_state, mouse_x)
        else:
            race_state.dragging_bars = False
            race_state.dragging_speed = False

        clock.tick(120)


# ============================================================
# RACE MODE
# ============================================================

def race_mode(race_state):
    if not race_settings_screen(race_state):
        return

    race_data = generate_values(race_state.shuffle_mode, race_state.bar_count)

    left = RaceSorter(race_data, race_state.algorithm_1)
    right = RaceSorter(race_data, race_state.algorithm_2)

    race_state.paused = False
    race_state.step_requested = False

    left_highlight = []
    right_highlight = []

    winner = None
    race_finished = False
    waiting_for_decision = False
    winner_announced = False

    exit_button = pygame.Rect(220, HEIGHT - 120, 240, 50)
    continue_button = pygame.Rect(540, HEIGHT - 120, 240, 50)

    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                raise SystemExit

            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    return

                if event.key == pygame.K_m:
                    toggle_sound()
                elif event.key == pygame.K_RIGHT and race_state.paused:
                    race_state.step_requested = True
                elif event.key == pygame.K_p and not waiting_for_decision:
                    race_state.paused = not race_state.paused
                elif waiting_for_decision:
                    if event.key in (pygame.K_RETURN, pygame.K_SPACE):
                        waiting_for_decision = False
                    elif event.key == pygame.K_x:
                        return

            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if waiting_for_decision:
                    if exit_button.collidepoint(event.pos):
                        return
                    if continue_button.collidepoint(event.pos):
                        waiting_for_decision = False
                elif race_finished:
                    return

        if not race_state.paused or race_state.step_requested:
            if not left.done:
                left_highlight = left.step()
                if left_highlight:
                    play_race_sound(left.data[left_highlight[0]], 0)

            if not right.done:
                right_highlight = right.step()
                if right_highlight:
                    play_race_sound(right.data[right_highlight[0]], 1)

            race_state.step_requested = False

        if not winner_announced and (left.done or right.done):
            winner_announced = True

            if left.done and not right.done:
                winner = left.algorithm
            elif right.done and not left.done:
                winner = right.algorithm
            else:
                # Both finished on the same frame - fall back to comparing
                # their recorded finish timestamps.
                if left.finished_time < right.finished_time:
                    winner = left.algorithm
                elif right.finished_time < left.finished_time:
                    winner = right.algorithm
                else:
                    winner = "TIE"

            waiting_for_decision = not (left.done and right.done)
            race_finished = left.done and right.done

        if left.done and right.done:
            race_finished = True
            if left.finished_time is not None and right.finished_time is not None:
                if left.finished_time < right.finished_time:
                    winner = left.algorithm
                elif right.finished_time < left.finished_time:
                    winner = right.algorithm
                else:
                    winner = "TIE"

        screen.fill(BACKGROUND)

        title = big_font.render("ALGORITHM RACE", True, WHITE)
        screen.blit(title, (WIDTH // 2 - title.get_width() // 2, 10))