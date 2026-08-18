"""Algorithm Visualizer - pygame app.

Sort/race logic lives in sorting_algorithms.py (no pygame dependency,
independently unit tested by test_algorithms.py). This file only handles
rendering, audio, input, and the two small pieces of mutable UI state
(AppState for the main view, RaceState for race mode) that used to be
spread across ~15 separate module-level globals.
"""

import math
import time
from array import array
from dataclasses import dataclass, field

import pygame

from sorting_algorithms import (
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
)

pygame.init()
pygame.mixer.init()

# ============================================================
# WINDOW
# ============================================================

WIDTH = 1000
HEIGHT = 800
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
# ~15 "global X" declarations the previous version needed. Functions
# take `state` as a parameter and mutate its attributes directly.

@dataclass
class AppState:
    num_bars: int = 80
    algorithm_index: int = 0
    shuffle_index: int = 0
    sort_delay: int = 20  # 50 = slow, 0 = maximum speed
    sorting: bool = False
    paused: bool = False
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


state = AppState()
race_state = RaceState()

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
# SLIDERS
# ============================================================
# Rects are static, so build them once instead of allocating a new
# pygame.Rect every frame. update_* functions share one ratio helper.

SPEED_SLIDER = pygame.Rect(600, GRAPH_HEIGHT + 95, 180, 8)
BAR_SLIDER = pygame.Rect(600, GRAPH_HEIGHT + 130, 180, 8)
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
    screen.blit(status_text, (20, GRAPH_HEIGHT + 40))

    stats = small_font.render(
        f"Comparisons: {state.comparisons}    Swaps: {state.swaps}    "
        f"Writes: {state.writes}    Time: {state.sort_time:.2f}s",
        True,
        GRAY,
    )
    screen.blit(stats, (20, GRAPH_HEIGHT + 62))

    start_button = pygame.Rect(20, GRAPH_HEIGHT + 95, 110, 38)
    if state.sorting:
        draw_button(start_button, "RESUME" if state.paused else "STOP", RED)
    else:
        draw_button(start_button, "START")

    algorithm_button = pygame.Rect(140, GRAPH_HEIGHT + 95, 170, 38)
    draw_button(algorithm_button, state.algorithm.upper())

    shuffle_button = pygame.Rect(320, GRAPH_HEIGHT + 95, 170, 38)
    draw_button(shuffle_button, state.shuffle_mode.upper())

    speed_text = small_font.render("Speed", True, TEXT_COLOR)
    screen.blit(speed_text, (520, GRAPH_HEIGHT + 89))

    pygame.draw.rect(screen, (80, 80, 80), SPEED_SLIDER, border_radius=4)
    speed_ratio = (50 - state.sort_delay) / 50
    speed_x = int(SPEED_SLIDER.x + speed_ratio * SPEED_SLIDER.width)
    pygame.draw.circle(screen, WHITE, (speed_x, SPEED_SLIDER.centery), 8)

    bars_text = small_font.render(f"Bars: {state.num_bars}", True, TEXT_COLOR)
    screen.blit(bars_text, (520, GRAPH_HEIGHT + 124))

    pygame.draw.rect(screen, (80, 80, 80), BAR_SLIDER, border_radius=4)
    bar_ratio = (state.num_bars - MIN_BARS) / (MAX_BARS - MIN_BARS)
    bar_x = int(BAR_SLIDER.x + bar_ratio * BAR_SLIDER.width)
    pygame.draw.circle(screen, WHITE, (bar_x, BAR_SLIDER.centery), 8)

    race_button = pygame.Rect(800, GRAPH_HEIGHT + 95, 160, 38)
    draw_button(race_button, "RACE MODE")

    controls = small_font.render(
        "SPACE = Start    R = Shuffle    TAB = Algorithm    "
        "P = Pause    M = Mute    ESC = Stop",
        True,
        GRAY,
    )
    screen.blit(controls, (20, GRAPH_HEIGHT + 150))

    return start_button, algorithm_button, shuffle_button, race_button


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
            elif event.key == pygame.K_m:
                toggle_sound()

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            stop_button = pygame.Rect(20, GRAPH_HEIGHT + 95, 110, 38)
            if stop_button.collidepoint(event.pos):
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
    processing events (so stop/mute/resume keep working) and redrawing
    the current frame with a "Paused" status."""

    while state.paused:
        if not process_sort_events(state):
            return False
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
    state.status = "Sorting..."
    state.reset_stats()

    stats = new_stats()
    state.sort_start_time = time.perf_counter()
    generator = SORT_GENERATORS[state.algorithm](state.values, stats)

    success = True

    for highlight in generator:
        state.comparisons = stats["comparisons"]
        state.swaps = stats["swaps"]
        state.writes = stats["writes"]

        if not process_sort_events(state):
            success = False
            break

        if state.paused:
            state.status = "Paused"
            if not wait_while_paused(state, highlight):
                success = False
                break
            state.status = "Sorting..."

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

    left_highlight = []
    right_highlight = []

    winner = None
    race_finished = False
    waiting_for_decision = False
    winner_announced = False

    exit_button = pygame.Rect(220, 720, 240, 50)
    continue_button = pygame.Rect(540, 720, 240, 50)

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

        if not race_state.paused:
            if not left.done:
                left_highlight = left.step()
                if left_highlight:
                    play_race_sound(left.data[left_highlight[0]], 0)

            if not right.done:
                right_highlight = right.step()
                if right_highlight:
                    play_race_sound(right.data[right_highlight[0]], 1)

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
        screen.blit(title, (WIDTH // 2 - title.get_width() // 2, 15))

        pygame.draw.line(screen, (80, 80, 80), (WIDTH // 2, 80), (WIDTH // 2, 680), 2)

        left_title = normal_font.render(
            left.algorithm, True, GREEN if winner == left.algorithm else TEXT_COLOR
        )
        right_title = normal_font.render(
            right.algorithm, True, GREEN if winner == right.algorithm else TEXT_COLOR
        )
        screen.blit(left_title, (250 - left_title.get_width() // 2, 65))
        screen.blit(right_title, (750 - right_title.get_width() // 2, 65))

        draw_bars(left.data, left_highlight, 0, WIDTH // 2)
        draw_bars(right.data, right_highlight, WIDTH // 2, WIDTH // 2)

        left_status = "FINISHED" if left.done else ("PAUSED" if race_state.paused else "RUNNING")
        right_status = "FINISHED" if right.done else ("PAUSED" if race_state.paused else "RUNNING")

        left_stats = small_font.render(
            f"{left_status}   Comparisons: {left.comparisons}   Swaps: {left.swaps}   "
            f"Writes: {left.writes}   Time: {left.elapsed():.2f}s",
            True,
            GREEN if left.done else GRAY,
        )
        right_stats = small_font.render(
            f"{right_status}   Comparisons: {right.comparisons}   Swaps: {right.swaps}   "
            f"Writes: {right.writes}   Time: {right.elapsed():.2f}s",
            True,
            GREEN if right.done else GRAY,
        )
        screen.blit(left_stats, (15, 690))
        screen.blit(right_stats, (515, 690))

        if waiting_for_decision:
            winner_text = title_font.render(f"[WINNER] {winner} WINS!", True, GREEN)
            screen.blit(winner_text, (WIDTH // 2 - winner_text.get_width() // 2, 515))

            question = normal_font.render(
                "Exit the race or watch the other algorithm finish?", True, WHITE
            )
            screen.blit(question, (WIDTH // 2 - question.get_width() // 2, 555))

            draw_button(exit_button, "EXIT RACE", RED)
            draw_button(continue_button, "LET OTHER FINISH")

            hint = small_font.render(
                "ENTER / SPACE = Let other finish    X / ESC = Exit", True, GRAY
            )
            screen.blit(hint, (WIDTH // 2 - hint.get_width() // 2, 785))

        elif race_finished:
            if winner == "TIE":
                winner_text = title_font.render("RESULT: TIE", True, WHITE)
            else:
                winner_text = title_font.render(f"[WINNER] {winner}", True, GREEN)

            screen.blit(winner_text, (WIDTH // 2 - winner_text.get_width() // 2, 730))

            hint = small_font.render("Click or press ESC to return", True, GRAY)
            screen.blit(hint, (WIDTH // 2 - hint.get_width() // 2, 765))

        else:
            race_text = small_font.render(
                "Race paused - P to resume" if race_state.paused else "Race in progress...",
                True,
                GRAY,
            )
            screen.blit(race_text, (WIDTH // 2 - race_text.get_width() // 2, 730))

            hint = small_font.render("P = Pause    M = Mute    ESC = Exit", True, GRAY)
            screen.blit(hint, (WIDTH // 2 - hint.get_width() // 2, 765))

        pygame.display.flip()

        if waiting_for_decision or race_state.paused:
            clock.tick(60)
        else:
            pygame.time.delay(race_state.speed)


# ============================================================
# MAIN LOOP
# ============================================================

def main():
    running = True

    while running:
        start_button, algorithm_button, shuffle_button, race_button = draw_panel(state)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_SPACE and not state.sorting:
                    run_sort(state)
                elif event.key == pygame.K_r and not state.sorting:
                    state.reshuffle()
                elif event.key == pygame.K_TAB and not state.sorting:
                    state.algorithm_index = (state.algorithm_index + 1) % len(ALGORITHMS)
                elif event.key == pygame.K_m:
                    toggle_sound()
                elif event.key == pygame.K_ESCAPE and state.sorting:
                    state.stop_requested = True

            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if start_button.collidepoint(event.pos):
                    if state.sorting:
                        state.stop_requested = True
                    else:
                        run_sort(state)
                elif algorithm_button.collidepoint(event.pos) and not state.sorting:
                    state.algorithm_index = (state.algorithm_index + 1) % len(ALGORITHMS)
                elif shuffle_button.collidepoint(event.pos) and not state.sorting:
                    state.shuffle_index = (state.shuffle_index + 1) % len(SHUFFLE_MODES)
                    state.reshuffle()
                elif SPEED_SLIDER.collidepoint(event.pos) and not state.sorting:
                    state.dragging_speed = True
                    update_speed(state, event.pos[0])
                elif BAR_SLIDER.collidepoint(event.pos) and not state.sorting:
                    state.dragging_bar_slider = True
                    update_bar_count(state, event.pos[0])
                elif race_button.collidepoint(event.pos) and not state.sorting:
                    race_mode(race_state)

            if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                state.dragging_speed = False
                state.dragging_bar_slider = False

        if state.dragging_speed and not state.sorting:
            if pygame.mouse.get_pressed()[0]:
                update_speed(state, pygame.mouse.get_pos()[0])
            else:
                state.dragging_speed = False

        if state.dragging_bar_slider and not state.sorting:
            if pygame.mouse.get_pressed()[0]:
                update_bar_count(state, pygame.mouse.get_pos()[0])
            else:
                state.dragging_bar_slider = False

        if state.sorting:
            state.sort_time = time.perf_counter() - state.sort_start_time

        screen.fill(BACKGROUND)
        draw_bars(state.values)
        draw_panel(state)
        pygame.display.flip()

        clock.tick(60)

    pygame.quit()


if __name__ == "__main__":
    main()
