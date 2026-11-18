"""
DARK SHADOW® - Advanced 3D Volumetric Particle Engine
Features:
- True 3D spherical volume with real-time perspective projection
- Fibonacci sphere surface shell + internal nebula core + Saturn-like celestial orbital aura
- Single-point bottom emergence (fountain singularity fanning into circular ring)
- Dynamic constellation energy interconnect lines
- Vectorized SIMD physics for 1,200 particles at 60 FPS
"""

import math
import time
import numpy as np
from typing import Tuple, List, Optional
from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QRadialGradient

from ..config import VisualConfig, PhysicsConfig, OrbState
from .animations import RippleManager, ease_out_cubic, ease_in_out_cubic


class ParticleSystem:
    """
    High-density 3D volumetric particle physics engine.
    Renders 1,200 living particles with perspective depth, constellation meshes,
    and single-point fountain emergence.
    """

    def __init__(self, visual_cfg: VisualConfig, physics_cfg: PhysicsConfig):
        self.vcfg = visual_cfg
        self.pcfg = physics_cfg
        self.n = self.vcfg.particle_count
        self.trail_len = self.vcfg.trail_length

        # State and timing
        self.state = OrbState.IDLE
        self.state_time = 0.0
        self.elapsed_time = 0.0
        self.overall_alpha = 0.0

        # Geometry anchors
        self.center_x = 210.0
        self.center_y = 210.0
        self.screen_bottom_y = 800.0
        self.current_radius = self.vcfg.base_radius
        self.floating_offset_x = 0.0
        self.floating_offset_y = 0.0

        # 3D Rotation angles
        self.rot_y = 0.0
        self.rot_x = 0.28  # Subtle tilt for perspective volume

        # Voice audio reactivity
        self.audio_amplitude = 0.0
        self.smoothed_amplitude = 0.0

        # Mouse interaction
        self.mouse_pos: Optional[Tuple[float, float]] = None
        self.is_hovered = False

        # Ripple manager
        self.ripples = RippleManager()

        # Initialize 3D particle state
        self._init_particles_3d()

    def _init_particles_3d(self):
        """Build 3D spherical layers using Fibonacci sphere distribution and nebula core."""
        n = self.n

        # Kinematic states in 2D projected space
        self.pos = np.zeros((n, 2), dtype=np.float32)
        self.vel = np.zeros((n, 2), dtype=np.float32)
        self.target_pos = np.zeros((n, 2), dtype=np.float32)

        # 3D spherical coordinate arrays: (theta, phi, r_ratio)
        self.theta = np.zeros(n, dtype=np.float32)
        self.phi = np.zeros(n, dtype=np.float32)
        self.r_ratio = np.zeros(n, dtype=np.float32)
        self.depth_z = np.zeros(n, dtype=np.float32)

        # Trail history
        self.trail = np.zeros((n, self.trail_len, 2), dtype=np.float32)

        # Layers: 0=Dense Nuclear Core, 1=Fibonacci Spherical Shell, 2=Celestial Orbital Aura
        n_shell = int(n * 0.55)    # 660 surface particles
        n_core = int(n * 0.25)     # 300 internal nebula particles
        n_aura = n - n_shell - n_core  # 240 outer cosmic ring particles

        self.layers = np.zeros(n, dtype=np.int32)
        self.layers[:n_core] = 0
        self.layers[n_core:n_core + n_shell] = 1
        self.layers[n_core + n_shell:] = 2

        # 1. Fibonacci Sphere for the outer surface shell (Layer 1)
        # Evenly spaces points on a 3D sphere surface without clumping
        golden_ratio = (1.0 + math.sqrt(5.0)) / 2.0
        indices = np.arange(n_shell)
        self.theta[n_core:n_core + n_shell] = (2.0 * math.pi * indices / golden_ratio).astype(np.float32)
        self.phi[n_core:n_core + n_shell] = np.arcsin(1.0 - 2.0 * (indices + 0.5) / n_shell).astype(np.float32)
        self.r_ratio[n_core:n_core + n_shell] = np.random.normal(1.0, 0.03, n_shell).clip(0.94, 1.06).astype(np.float32)

        # 2. Internal Nebula Core (Layer 0) - Volumetric 3D density
        self.theta[:n_core] = np.random.uniform(0, 2 * math.pi, n_core).astype(np.float32)
        self.phi[:n_core] = np.random.uniform(-math.pi / 2, math.pi / 2, n_core).astype(np.float32)
        self.r_ratio[:n_core] = np.random.uniform(0.15, 0.82, n_core).astype(np.float32)

        # 3. Celestial Orbital Aura / Saturn Rings (Layer 2)
        self.theta[n_core + n_shell:] = np.random.uniform(0, 2 * math.pi, n_aura).astype(np.float32)
        # Flattened elevation close to ring plane
        self.phi[n_core + n_shell:] = np.random.normal(0.0, 0.12, n_aura).astype(np.float32)
        self.r_ratio[n_core + n_shell:] = np.random.uniform(1.10, 1.45, n_aura).astype(np.float32)

        # Tendril magnetic particles (~15%)
        self.is_tendril = (np.random.rand(n) < 0.15)

        # Sizes & Phases
        self.base_sizes = np.random.uniform(self.vcfg.min_particle_size, self.vcfg.max_particle_size, n).astype(np.float32)
        self.base_sizes[self.layers == 1] *= 1.15
        self.sizes = self.base_sizes.copy()
        self.phases = np.random.uniform(0, 2 * math.pi, n).astype(np.float32)

        # Color palette assignment [R, G, B, BaseAlpha]
        self.colors = np.zeros((n, 4), dtype=np.float32)
        for i in range(n):
            if self.layers[i] == 0:
                # Core: radiant white and subtle ice blue
                self.colors[i] = [255, 255, 255, 240] if np.random.rand() > 0.4 else [224, 242, 254, 220]
            elif self.layers[i] == 1:
                # Shell: electric cyan, ice blue, and pure white stars
                p = np.random.rand()
                if p < 0.35:
                    self.colors[i] = [56, 189, 248, 230]   # Sky Cyan
                elif p < 0.65:
                    self.colors[i] = [34, 211, 238, 240]   # Electric Neon Cyan
                elif p < 0.85:
                    self.colors[i] = [255, 255, 255, 255]   # White Star
                else:
                    self.colors[i] = [129, 140, 248, 210]   # Indigo Cosmic Accent
            else:
                # Aura: translucent cyan-violet dust
                self.colors[i] = [56, 189, 248, 160] if np.random.rand() > 0.5 else [165, 180, 252, 140]

        # Initialize dormant positions
        self.pos[:, 0] = self.center_x
        self.pos[:, 1] = self.center_y

    def set_center(self, cx: float, cy: float):
        self.center_x = cx
        self.center_y = cy

    def set_screen_bottom(self, bottom_y: float):
        self.screen_bottom_y = bottom_y

    def set_state(self, new_state: OrbState):
        if self.state == new_state:
            return
        self.state = new_state
        self.state_time = 0.0

        if new_state == OrbState.ACTIVATING:
            self._start_activation()
        elif new_state == OrbState.DEACTIVATING:
            self._start_deactivation()
        elif new_state == OrbState.IDLE:
            self.overall_alpha = 0.0

    def trigger_click_shockwave(self, click_x: float, click_y: float):
        self.ripples.spawn(
            cx=click_x,
            cy=click_y,
            max_radius=self.vcfg.base_radius * 2.4,
            speed=340.0,
            amplitude=24.0,
            width=32.0
        )

    def trigger_scroll_ripple(self, delta: int):
        direction = 1.0 if delta > 0 else -1.0
        self.ripples.spawn(
            cx=self.center_x + self.floating_offset_x,
            cy=self.center_y + self.floating_offset_y,
            max_radius=self.vcfg.base_radius * 2.0,
            speed=280.0 * direction,
            amplitude=18.0,
            width=26.0
        )
        # Impart rotational kick
        self.rot_y += direction * 0.45

    def set_audio_amplitude(self, amplitude: float):
        self.audio_amplitude = max(0.0, min(1.0, amplitude))

    def _start_activation(self):
        """
        USER REQUIREMENT:
        All particles emerge from ONE SINGLE POINT at the bottom edge of the screen!
        They erupt upward in a fountain, spread outward in a circular formation,
        and assemble into the perfectly round glowing 3D orb.
        """
        n = self.n
        self.overall_alpha = 0.0

        # EXACT SINGLE POINT ORIGIN AT SCREEN BOTTOM
        origin_x = self.center_x
        origin_y = self.screen_bottom_y

        self.pos[:, 0] = origin_x
        self.pos[:, 1] = origin_y

        # Fountain emission: Fanning cone upward
        # Spread angles from -60 deg to +60 deg
        cone_angles = np.linspace(-math.pi * 0.38, math.pi * 0.38, n).astype(np.float32)
        cone_angles += np.random.uniform(-0.06, 0.06, n).astype(np.float32)

        # High upward launch speed with fountain curve
        speeds = np.random.uniform(420.0, 680.0, n).astype(np.float32)
        self.vel[:, 0] = np.sin(cone_angles) * speeds * 0.65
        self.vel[:, 1] = -np.cos(cone_angles) * speeds

        # Reset trails to the single emission point
        for t in range(self.trail_len):
            self.trail[:, t, 0] = origin_x
            self.trail[:, t, 1] = origin_y

    def _start_deactivation(self):
        angles = np.random.uniform(0, 2 * math.pi, self.n).astype(np.float32)
        drift = np.random.uniform(25.0, 85.0, self.n).astype(np.float32)
        self.vel[:, 0] += np.cos(angles) * drift
        self.vel[:, 1] += np.random.uniform(35.0, 110.0, self.n).astype(np.float32)

    def update(self, dt: float):
        if dt <= 0.0 or dt > 0.1:
            dt = 0.016

        self.elapsed_time += dt
        self.state_time += dt

        # Smooth audio amplitude
        if self.audio_amplitude > self.smoothed_amplitude:
            self.smoothed_amplitude += (self.audio_amplitude - self.smoothed_amplitude) * min(1.0, dt * 15.0)
        else:
            self.smoothed_amplitude += (self.audio_amplitude - self.smoothed_amplitude) * min(1.0, dt * 6.0)

        # Rotate 3D volume calmly on axis without wild dancing
        spin_speed = 0.12 if self.state != OrbState.THINKING else 0.85
        self.rot_y += spin_speed * dt

        self.ripples.update(dt)

        if self.state == OrbState.IDLE:
            self.overall_alpha = 0.0
            return
        elif self.state == OrbState.ACTIVATING:
            self._update_activating(dt)
        elif self.state == OrbState.DEACTIVATING:
            self._update_deactivating(dt)
        else:
            self._update_active_states(dt)

        # Advance trail history
        self.trail[:, 1:, :] = self.trail[:, :-1, :]
        self.trail[:, 0, :] = self.pos

    def _calculate_3d_projection(self, expansion: float):
        """
        Calculates 3D sphere coordinates, rotates them in 3D space,
        and projects onto 2D plane with perspective depth.
        """
        t = self.elapsed_time
        cx = self.center_x + self.floating_offset_x
        cy = self.center_y + self.floating_offset_y

        breath = math.sin(t * self.vcfg.breathing_speed) * self.vcfg.breathing_amplitude
        effective_r = self.vcfg.base_radius + breath + expansion
        self.current_radius = effective_r

        # Radii per particle
        r = effective_r * self.r_ratio

        # 3D rotation angles
        rot_y = self.rot_y
        rot_x = self.rot_x

        # Spherical to 3D Cartesian
        cos_phi = np.cos(self.phi)
        sin_phi = np.sin(self.phi)
        th = self.theta + rot_y

        x0 = r * cos_phi * np.sin(th)
        y0 = r * sin_phi
        z0 = r * cos_phi * np.cos(th)

        # Pitch tilt around X-axis
        cos_rx = math.cos(rot_x)
        sin_rx = math.sin(rot_x)
        x3 = x0
        y3 = y0 * cos_rx - z0 * sin_rx
        z3 = y0 * sin_rx + z0 * cos_rx

        self.depth_z = z3

        # Perspective projection
        focal_length = 340.0
        proj_scale = focal_length / (focal_length + z3 * 0.45)

        self.target_pos[:, 0] = cx + x3 * proj_scale
        self.target_pos[:, 1] = cy + y3 * proj_scale

    def _update_activating(self, dt: float):
        """Fountain emergence from bottom single point into 3D orb."""
        duration = self.vcfg.activate_duration
        progress = min(1.0, self.state_time / duration)

        self.overall_alpha = ease_out_cubic(min(1.0, progress * 1.5))
        self._calculate_floating()
        self._calculate_3d_projection(expansion=0.0)

        homing_weight = ease_in_out_cubic(progress)

        dx = self.target_pos[:, 0] - self.pos[:, 0]
        dy = self.target_pos[:, 1] - self.pos[:, 1]

        # Spiral vortex during flight
        if progress < 0.65:
            vortex_strength = (1.0 - progress) * 16.0
            dist = np.sqrt(dx * dx + dy * dy) + 1.0
            self.vel[:, 0] += (-dy / dist) * vortex_strength
            self.vel[:, 1] += (dx / dist) * vortex_strength

        # Homing spring force
        spring = 0.03 + 0.15 * homing_weight
        self.vel[:, 0] += dx * spring
        self.vel[:, 1] += dy * spring

        damping = 0.91 + 0.04 * (1.0 - homing_weight)
        self.vel *= damping
        self.pos += self.vel * (dt * 60.0)

        if progress >= 1.0:
            self.set_state(OrbState.INTERACTING)

    def _update_deactivating(self, dt: float):
        duration = self.vcfg.deactivate_duration
        progress = min(1.0, self.state_time / duration)
        self.overall_alpha = max(0.0, 1.0 - ease_out_cubic(progress))

        self.vel[:, 1] += 55.0 * dt
        self.vel *= 0.95
        self.pos += self.vel * (dt * 60.0)

        if progress >= 1.0:
            self.set_state(OrbState.IDLE)

    def _update_active_states(self, dt: float):
        self.overall_alpha = 1.0
        self._calculate_floating()

        audio_exp = self.smoothed_amplitude * self.pcfg.audio_radius_scale
        if self.state == OrbState.LISTENING:
            audio_exp *= 1.5

        self._calculate_3d_projection(expansion=audio_exp)

        # 1. Spring force to 3D projected target
        dx = self.target_pos[:, 0] - self.pos[:, 0]
        dy = self.target_pos[:, 1] - self.pos[:, 1]
        self.vel[:, 0] += dx * self.pcfg.spring_cohesion
        self.vel[:, 1] += dy * self.pcfg.spring_cohesion

        # 2. State dynamics
        if self.state in (OrbState.LISTENING, OrbState.SPEAKING) and self.smoothed_amplitude > 0.02:
            self._apply_audio_vibration()

        # 3. Mouse interaction
        if self.mouse_pos is not None:
            self._apply_mouse_interaction(self.mouse_pos[0], self.mouse_pos[1])

        # 4. Ripples
        self._apply_ripples()

        # 5. Organic Brownian jitter
        self.vel[:, 0] += np.random.uniform(-self.pcfg.brownian_strength, self.pcfg.brownian_strength, self.n)
        self.vel[:, 1] += np.random.uniform(-self.pcfg.brownian_strength, self.pcfg.brownian_strength, self.n)

        # 6. Damping & Integration
        self.vel *= self.pcfg.damping
        self.pos += self.vel * (dt * 60.0)

    def _calculate_floating(self):
        # Keep anchor stable and grounded on desktop (no erratic drifting)
        self.floating_offset_x = 0.0
        self.floating_offset_y = 0.0

    def _apply_audio_vibration(self):
        cx = self.center_x + self.floating_offset_x
        cy = self.center_y + self.floating_offset_y
        rx = self.pos[:, 0] - cx
        ry = self.pos[:, 1] - cy
        dist = np.sqrt(rx * rx + ry * ry) + 0.1

        harmonic = np.sin(self.theta * 5.0 + self.elapsed_time * 26.0)
        vibe = harmonic * self.smoothed_amplitude * self.pcfg.audio_jitter_scale
        self.vel[:, 0] += (rx / dist) * vibe
        self.vel[:, 1] += (ry / dist) * vibe

    def _apply_mouse_interaction(self, mx: float, my: float):
        dx = self.pos[:, 0] - mx
        dy = self.pos[:, 1] - my
        dist = np.sqrt(dx * dx + dy * dy) + 0.1

        repel = dist < self.pcfg.mouse_repel_radius
        if np.any(repel):
            sub_d = dist[repel]
            factor = (1.0 - (sub_d / self.pcfg.mouse_repel_radius)) ** 2
            force = factor * self.pcfg.mouse_repel_force
            self.vel[repel, 0] += (dx[repel] / sub_d) * force
            self.vel[repel, 1] += (dy[repel] / sub_d) * force

        attract = self.is_tendril & (dist < self.pcfg.mouse_attract_radius) & (dist > 35.0)
        if np.any(attract):
            sub_d = dist[attract]
            force = (1.0 - (sub_d / self.pcfg.mouse_attract_radius)) * self.pcfg.mouse_attract_force
            self.vel[attract, 0] -= (dx[attract] / sub_d) * force
            self.vel[attract, 1] -= (dy[attract] / sub_d) * force

    def _apply_ripples(self):
        for ripple in self.ripples.ripples:
            if not ripple.alive:
                continue
            dx = self.pos[:, 0] - ripple.cx
            dy = self.pos[:, 1] - ripple.cy
            dist = np.sqrt(dx * dx + dy * dy) + 0.1

            diff = np.abs(dist - ripple.radius)
            mask = diff < ripple.width
            if np.any(mask):
                intensity = np.cos((diff[mask] / ripple.width) * (math.pi / 2.0))
                disp = intensity * ripple.amplitude * ripple.intensity
                self.vel[mask, 0] += (dx[mask] / dist[mask]) * disp
                self.vel[mask, 1] += (dy[mask] / dist[mask]) * disp

    def render(self, painter: QPainter):
        """Render 3D volumetric particles, constellation web, and glowing core."""
        if self.overall_alpha <= 0.005:
            return

        alpha_mul = self.overall_alpha
        cx = self.center_x + self.floating_offset_x
        cy = self.center_y + self.floating_offset_y

        # 1. Multi-layered glowing atmosphere
        self._render_central_glow(painter, cx, cy, alpha_mul)

        # 2. Render particle trails
        if self.state in (OrbState.ACTIVATING, OrbState.THINKING) or self.smoothed_amplitude > 0.15:
            self._render_trails(painter, alpha_mul)

        # 3. Constellation Energy Web (Connecting nearest surface particles)
        if self.vcfg.enable_constellation_lines and self.state != OrbState.ACTIVATING:
            self._render_constellation_web(painter, alpha_mul)

        # 4. Render particles sorted by 3D depth (back to front)
        self._render_particles_3d(painter, alpha_mul)

    def _render_central_glow(self, painter: QPainter, cx: float, cy: float, alpha_mul: float):
        r = self.current_radius
        grad = QRadialGradient(QPointF(cx, cy), r * 1.4)

        if self.state == OrbState.LISTENING:
            c_core = QColor(56, 189, 248, int(85 * alpha_mul))
            c_mid = QColor(34, 211, 238, int(45 * alpha_mul))
        elif self.state == OrbState.THINKING:
            c_core = QColor(147, 197, 253, int(80 * alpha_mul))
            c_mid = QColor(99, 102, 241, int(40 * alpha_mul))
        elif self.state == OrbState.SPEAKING:
            c_core = QColor(255, 255, 255, int(100 * alpha_mul))
            c_mid = QColor(56, 189, 248, int(50 * alpha_mul))
        else:
            c_core = QColor(186, 220, 248, int(55 * alpha_mul))
            c_mid = QColor(56, 189, 248, int(25 * alpha_mul))

        grad.setColorAt(0.0, c_core)
        grad.setColorAt(0.48, c_mid)
        grad.setColorAt(1.0, QColor(0, 0, 0, 0))

        painter.setBrush(QBrush(grad))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(cx, cy), r * 1.4, r * 1.4)

    def _render_constellation_web(self, painter: QPainter, alpha_mul: float):
        """Draw delicate holographic filaments between adjacent surface shell particles."""
        # Consider a subset of surface shell particles with positive depth (front-facing)
        shell_mask = (self.layers == 1) & (self.depth_z > -10.0)
        indices = np.where(shell_mask)[0]
        if len(indices) < 2:
            return

        # Sample ~120 particles for constellation check for 60 FPS performance
        sample_indices = np.random.choice(indices, min(120, len(indices)), replace=False)
        pts = self.pos[sample_indices]
        max_dist = self.vcfg.constellation_max_distance

        for i in range(len(sample_indices)):
            p1 = pts[i]
            for j in range(i + 1, min(i + 8, len(sample_indices))):
                p2 = pts[j]
                dx = p1[0] - p2[0]
                dy = p1[1] - p2[1]
                dist = math.sqrt(dx * dx + dy * dy)
                if dist < max_dist:
                    line_alpha = int((1.0 - dist / max_dist) * 85 * alpha_mul)
                    if line_alpha > 5:
                        painter.setPen(QPen(QColor(56, 189, 248, line_alpha), 0.9))
                        painter.drawLine(QPointF(p1[0], p1[1]), QPointF(p2[0], p2[1]))

    def _render_trails(self, painter: QPainter, alpha_mul: float):
        speeds_sq = self.vel[:, 0] * self.vel[:, 0] + self.vel[:, 1] * self.vel[:, 1]
        active = np.where(speeds_sq > 25.0)[0]

        for i in active:
            r, g, b, base_a = self.colors[i]
            for t in range(self.trail_len - 1):
                fade = (1.0 - t / self.trail_len) * 0.4 * alpha_mul
                seg_a = int(base_a * fade)
                if seg_a < 4:
                    continue
                p1 = QPointF(float(self.trail[i, t, 0]), float(self.trail[i, t, 1]))
                p2 = QPointF(float(self.trail[i, t + 1, 0]), float(self.trail[i, t + 1, 1]))
                pen = QPen(QColor(int(r), int(g), int(b), seg_a), self.sizes[i] * 0.7)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                painter.setPen(pen)
                painter.drawLine(p1, p2)

    def _render_particles_3d(self, painter: QPainter, alpha_mul: float):
        """Render particles with 3D depth attenuation (back particles dimmer/smaller)."""
        painter.setPen(Qt.PenStyle.NoPen)
        n = self.n

        # Sort particles by 3D depth Z (render back particles first, front particles last)
        depth_order = np.argsort(self.depth_z)

        # Normalize depth factor: 0.0 (deepest back) to 1.0 (closest front)
        r_max = self.current_radius * 1.2
        depth_factor = np.clip((self.depth_z + r_max) / (2.0 * r_max + 0.1), 0.0, 1.0)

        audio_boost = 1.0 + (self.smoothed_amplitude * 0.45)

        for i in depth_order:
            x = float(self.pos[i, 0])
            y = float(self.pos[i, 1])
            r, g, b, base_a = self.colors[i]

            df = depth_factor[i]
            # Particles in front are brighter and larger; back are dimmer
            depth_alpha = 0.35 + 0.65 * df
            final_a = int(base_a * depth_alpha * alpha_mul)
            if final_a <= 3:
                continue

            # Fine crisp starlight dots (0.8 - 1.8 px)
            size = float(self.sizes[i] * (0.8 + 0.3 * df) * audio_boost)
            size = max(0.8, min(2.0, size))

            painter.setBrush(QBrush(QColor(int(r), int(g), int(b), final_a)))
            painter.drawEllipse(QPointF(x, y), size, size)
