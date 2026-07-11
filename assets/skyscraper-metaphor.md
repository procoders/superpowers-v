# Why Two Pre-Flights — The Skyscraper Metaphor

A 3-panel comic and a technical diagram explaining what Compound V's Phase 1 (parallel archaeology + domain-expert) actually protects against.

**Two layers of "missed reality":**
- **Archaeology** = what the existing **building** is (measure before you stack)
- **Domain advisor** = what the **building code** requires (legal cantilever, zoning, fire-egress)

Skip either and you ship something that's either physically wrong or legally wrong. Often both.

---

## The Story (Comic, 3 Panels)

### Panel 1 — The Customer's Request

```mermaid
flowchart LR
    Customer["👤 Customer<br/>'I need 500m² more space'"] --> Tower["🏢 Existing skyscraper<br/>(floor area: 200m²)"]
    style Customer fill:#fff4e0,stroke:#cc7700
    style Tower fill:#e6f0ff,stroke:#003d99
```

**Customer says:** "Add 500m² to my building."
**The building says nothing.** Nobody's checked what it actually is.

---

### Panel 2A — Without Archaeology: The Ugly Hat

```mermaid
flowchart TB
    Hat["🎩 NEW 'floor': 500m²<br/>(overhangs by 300m² on every side)<br/>━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━<br/>STRUCTURAL: unsupported overhang<br/>VISUAL: ridiculous<br/>USABLE: ~200m² (the rest hangs in air)"]
    F5["Floor 5 — 200m²"]
    F4["Floor 4 — 200m²"]
    F3["Floor 3 — 200m²"]
    F2["Floor 2 — 200m²"]
    F1["Floor 1 — 200m²"]

    Hat --> F5 --> F4 --> F3 --> F2 --> F1

    style Hat fill:#ffd6d6,stroke:#cc0000,stroke-width:3px
    style F1 fill:#e6f0ff
    style F2 fill:#e6f0ff
    style F3 fill:#e6f0ff
    style F4 fill:#e6f0ff
    style F5 fill:#e6f0ff
```

**Agent took the brief literally.** Built one 500m² floor on top of a 200m² tower. The overhang is unsupported. Most of the new "space" hangs in mid-air. The customer asked for 500m²; they got 200m² of usable space and a structural liability.

**In code terms:** the agent shipped a feature that *looks* like the spec but sits on assumptions the existing code can't support. Hidden coupling fires in production.

---

### Panel 2B — With Archaeology: Three Proper Floors

```mermaid
flowchart TB
    N3["NEW Floor 8 — 200m²"]
    N2["NEW Floor 7 — 200m²"]
    N1["NEW Floor 6 — 200m²"]
    F5["Floor 5 — 200m²"]
    F4["Floor 4 — 200m²"]
    F3["Floor 3 — 200m²"]
    F2["Floor 2 — 200m²"]
    F1["Floor 1 — 200m²"]

    N3 --> N2 --> N1 --> F5 --> F4 --> F3 --> F2 --> F1

    style N1 fill:#d6ffd6,stroke:#006600,stroke-width:2px
    style N2 fill:#d6ffd6,stroke:#006600,stroke-width:2px
    style N3 fill:#d6ffd6,stroke:#006600,stroke-width:2px
    style F1 fill:#e6f0ff
    style F2 fill:#e6f0ff
    style F3 fill:#e6f0ff
    style F4 fill:#e6f0ff
    style F5 fill:#e6f0ff
```

**Agent measured first.** Discovered the floor area is 200m². Proposed three proper 200m² floors instead of one mutant. Customer wanted 500m² and got **600m²** of usable, supported, beautiful space.

**In code terms:** the agent ran code-archaeology, saw the actual matrix (server types, shared state, sibling paths), and proposed a design that fits — extending what exists instead of stapling a foreign block on top.

---

### Panel 3 — The Lesson

```mermaid
flowchart LR
    A["Skip archaeology<br/>📐 Design from brief alone"] -->|"Ship fast,<br/>break later"| B["🎩 Ugly hat<br/>500m² promised<br/>200m² delivered<br/>+ liability"]
    C["Run archaeology<br/>🔍 Measure first, design second"] -->|"Slight delay,<br/>real solution"| D["🏗️ Three floors<br/>600m² delivered<br/>+ structural"]

    style A fill:#ffd6d6,stroke:#cc0000
    style B fill:#ffd6d6,stroke:#cc0000
    style C fill:#d6ffd6,stroke:#006600
    style D fill:#d6ffd6,stroke:#006600
```

**The 10 minutes you spend on archaeology buys you the difference between an ugly hat and three real floors.**

---

## The Technical View

Same story, mapped onto Compound V's three phases (with parallel pre-flight 1A + 1B + 1C):

> *Period piece: this diagram predates per-job isolation ("no worktrees" was the v0.1 stance — external workers now get git worktrees + the scope gate) and the v2.7 pre-brainstorm recon (Trigger 0); it keeps the original shape because the metaphor hasn't changed.*

```mermaid
flowchart TB
    subgraph Default["❌ Default Superpowers (no archaeology)"]
        direction LR
        B1["brainstorming<br/>(imagines the building)"] --> P1["writing-plans<br/>(designs the hat)"]
        P1 --> X1["sequential implementer<br/>on cheap model"]
        X1 --> Y1["🎩 Ugly hat shipped<br/>Coupling bugs surface in prod"]
    end

    subgraph Compound["✅ Compound V (parallel pre-flight + partitioning + parallel Opus)"]
        direction LR
        B2["brainstorming"] --> A2A["🔬 PHASE 1A<br/>code-archaeology<br/>(measures the building)"]
        B2 --> A2B["🧠 PHASE 1B<br/>domain-expert advisor<br/>(reads the building code)"]
        A2A --> P2["writing-plans<br/>+ 🧩 PHASE 2<br/>Disjoint Partition Map"]
        A2B --> P2
        P2 --> X2["🚀 PHASE 3<br/>N implementers on Opus,<br/>in parallel,<br/>no worktrees,<br/>scope-locked"]
        X2 --> Y2["🏗️ Three floors shipped<br/>Fits existing structure<br/>Passes inspection<br/>Parallel = wall-clock fast"]
    end

    style Default fill:#fff0f0,stroke:#cc0000
    style Compound fill:#f0fff0,stroke:#006600
    style Y1 fill:#ffd6d6
    style Y2 fill:#d6ffd6
    style A2A fill:#fffae6,stroke:#cc7700,stroke-width:2px
    style A2B fill:#e6f3ff,stroke:#0066cc,stroke-width:2px
    style P2 fill:#fffae6,stroke:#cc7700,stroke-width:2px
    style X2 fill:#fffae6,stroke:#cc7700,stroke-width:2px
```

### The trade

| Dimension | Default Superpowers | Compound V |
|---|---|---|
| Time to plan | Fast (skip audit) | +10 min for audit |
| Time to execute | Slow (sequential, N tasks = N×) | Fast (parallel, N tasks ≈ 1×) |
| Model cost per task | Cheap | Opus (~5× per task) |
| Cost of rework when coupling breaks | High (debug in prod) | Low (caught at design) |
| **Result for the customer** | 🎩 **Hat** | 🏗️ **Three floors** |

---

## TL;DR

> **Measure the building. Read the building code. Partition before you parallelize. Then go fast on the strong model.**
