# FP Layer Exporter

A nightmarish Blender exporter that breaks down modular 3D first-person models into layered 2D sprite components, enabling the creation of highly modular retro FPS weapon and equipment systems.

Animate normally in 3D. The exporter handles the rest.

---

# Features

* No manually maintained View Layers
* Object-based category assignment directly from the UI
* Automatic depth-aware weapon splitting
* Modular Body, Armor, and Weapon layers
* Current Frame export
* Timeline export
* Keyed Frame export
* Transparent PNG output
* Automatic WeaponTop / WeaponBottom generation
* Optional source render preservation for debugging

---

# Why This Exists

Traditional sprite pipelines force a choice:

### Bake Everything Together

```text
Weapon
Hands
Armor
```

Pros:

* Easy

Cons:

* No modularity
* No equipment swapping
* No armor customization

---

### Manually Author Front/Back Layers

```text
Weapon Back
Hands
Weapon Front
```

Pros:

* Modular

Cons:

* Pain
* Lots of pain
* Huge animation labor overhead

---

This exporter automates the process.

Animate a normal 3D rig and let Blender determine which parts of a weapon belong in front of the hands and which belong behind them. At runtime, animate them together on synced frames, and viola. A modular character.

---

# How It Works

The exporter renders several source passes.

### WeaponFull

The weapon rendered by itself.

### WeaponVisible

The weapon rendered while Body objects act as invisible depth occluders.

Only weapon pixels visible to the camera survive.

### Body

The player's hands and arms.

### Armor

Optional armor overlays.

---

The exporter then generates:

```text
WeaponTop    = WeaponVisible
WeaponBottom = WeaponFull - WeaponVisible
```

Resulting runtime layer order:

```text
WeaponBottom
Body
Armor
WeaponTop
```

This preserves correct weapon overlap automatically across every animation frame.

---

# Object Categories

Objects are assigned directly inside the addon panel.

No View Layers required.

## Weapon Objects

Anything that should be automatically split into front and back layers.

Examples:

* Swords
* Axes
* Maces
* Shields
* Torches
* Spell foci
* Offhand items

## Body Objects

The player's hands and arms.

Used as:

* Visible body sprites
* Depth occluders during weapon splitting

## Armor Objects

Optional overlays rendered between Body and WeaponTop.

Examples:

* Bracers
* Sleeves
* Gloves
* Plate armor
* Fur cuffs

---

# Export Modes

## Current Frame

Exports only the active frame.

---

## Timeline Frames

Exports a frame range using a configurable interval.

Example:

```text
Start Frame: 0
End Frame: 60
Interval: 5
```

Produces:

```text
0
5
10
15
...
60
```

---

## Keyed Category Frames

Scans animation keyframes only on assigned Weapon, Body, and Armor objects.

Useful for sprite workflows where only meaningful poses should be exported.

---

# Output Structure

Example:

```text
WeaponBottom/
    IronSword/
        Attack_IronSword_Bottom_00.png

Body/
    Human/
        Attack_Human_00.png

Armor/
    LeatherBracer/
        Attack_LeatherBracer_00.png

WeaponTop/
    IronSword/
        Attack_IronSword_Top_00.png
```

---

# Recommended Workflow

1. Build and animate normally in 3D.
2. Assign objects to Weapon, Body, and Armor categories.
3. Export.
4. Import generated layers into your engine.
5. Composite layers at runtime.

Suggested runtime order:

```text
WeaponBottom
Body
Armor
WeaponTop
```

---

# Recommended Camera Setup

For first-person sprite generation:

```text
Camera Type: Orthographic
Aspect Ratio: 1:1
Resolution: 1024×1024
```

This leaves room for:

* Slashes
* Thrusts
* Dual wielding
* Shields
* Spellcasting
* Large weapons

without requiring constant camera adjustments.

---

# Why This Is Weird

Most sprite pipelines render:

```text
3D Model
→ Sprite Sheet
→ Done
```

This pipeline renders:

```text
3D Model
→ Categorize Objects
→ Render WeaponFull
→ Render WeaponVisible
→ Render Body
→ Render Armor
→ Depth Analysis
→ Generate WeaponTop
→ Generate WeaponBottom
→ Export Layer Stack
→ Runtime Recomposition
```

It is objectively ridiculous.

It is also extremely effective.

Instead of manually deciding which parts of a weapon belong in front of a hand, the exporter simply asks Blender's depth buffer and uses the answer.

The result is a modular sprite workflow capable of producing equipment combinations that would be impractical to author by hand.

---

# Ideal Use Cases

* Retro FPS games
* Doom-style shooters
* Build Engine-inspired games
* Sprite-based action RPGs
* Modular first-person equipment systems
* Pre-rendered weapon animation pipelines

---

# Credits

Created by Vi.

Built for generating modular first-person sprite layers from animated 3D assets.

A horrifying amount of effort was spent so artists would never have to manually paint WeaponTop and WeaponBottom layers again.
