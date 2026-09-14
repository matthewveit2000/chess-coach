# Lessons Learned and Operational Processes

This document records the architectural evolution, operational processes, design decisions, and engineering lessons learned during the development of the Chess Coach tool and dashboard.

---

## 1. Architectural Evolution

### From In-Chat Graphics to the "One Stop Shop"
* **Initial State:** Analysis results were reported via CLI (`chess-coach review`, `chess-coach brief`) and textual terminal tables. Attempts to render complex SVG boards and charts directly inline within chat sessions encountered severe viewport constraints, touch incompatibilities, and poor mobile readability.
* **The Pivot:** The user mandated a single, permanent, mobile-optimized standalone HTML document (`index.html`) hosted publicly on **GitHub Pages**:
  * **Live Site:** `https://matthewveit2000.github.io/chess-coach/`
  * **Repository File:** `https://github.com/matthewveit2000/chess-coach/blob/main/index.html`
* **Architectural Advantage:** Bundling the data, CSS, and interactive SVG logic into a single self-contained document eliminates the need for a web backend, guarantees zero latency, works offline, and loads in milliseconds on any mobile device.

---

## 2. Mandatory Operational Rules

### The Two Standing Links
Every AI agent response must end with the active links:
1. `https://matthewveit2000.github.io/chess-coach/`
2. `https://github.com/matthewveit2000/chess-coach/blob/main/index.html`

### The AI Coach Tips Protocol
* **Rule:** Whenever the dashboard is updated with new games, the AI agent must personally inspect every non-best move (Inaccuracy, Mistake, Miss, Blunder) and write concise coaching tips.
* **Evaluation Checklist:**
  1. Inspect the board position (`fen_before`).
  2. Examine the move played vs. Stockfish's top recommendation (`best_san`).
  3. Review the opponent's reply and tactical threat from `reply_pv`.
  4. Note any tagged motifs (`hangs_piece`, `missed_fork`, `king_safety`, etc.).
  5. Formulate a **1–2 sentence**, club-level tip explaining:
     - **The Error:** What specific piece was hung, which tactic was overlooked, or what threat was ignored.
     - **The Fix:** What the engine's move accomplishes (defends material, creates counter-threats, locks down the center).
* **Anti-Pattern to Avoid:** Never use vague template filler like *"Playing `san` surrenders the initiative and lets opponent take control."* Be concrete: *"9... b6 ignores White's 9. Nd5 attacking your queen on d8. 9... c5 or 9... Qd8 was vital to neutralize the knight."*

---

## 3. Key Technical Lessons & Bug Fixes

### Bug 1: JavaScript Variable Scope Crash in Stepper
* **Symptom:** Tapping `Next ▶` or `◀ Prev` did not advance moves; board appeared completely frozen.
* **Root Cause:** In `updateBoardView()`, `const cls` was declared inside an `if (showArrows)` block. Later in the function, `coachClassification.className` accessed `cls`, throwing an uncaught `ReferenceError: cls is not defined` whenever arrows were disabled or when JavaScript block scoping isolated `cls`.
* **Lesson Learned:** Always declare state and classification variables at the top function level before entering conditional blocks.

### Bug 2: Distorted SVG Piece Artwork
* **Symptom:** Pieces looked strange, thin, or distorted on high-density displays.
* **Root Cause:** Simplified custom vector path approximations were used.
* **Lesson Learned:** Only use official, tournament-standard Wikimedia/Lichess `cburnett` vector SVG pieces defined inside `<defs>` (`#piece-P`, `#piece-N`, etc.). Render them inside a `<g>` container scaled dynamically:
  ```javascript
  const scale = sqSize / 45;
  g.setAttribute('transform', `translate(${x}, ${y}) scale(${scale})`);
  ```

### Bug 3: SVG Chart Rendering in Hidden Tabs
* **Symptom:** Switching to the Chart tab showed an empty or broken visualization.
* **Root Cause:** Elements inside elements with `display: none` return `0` for `getBoundingClientRect()`, causing layout calculations to fail during initial page load.
* **Lesson Learned:**
  * Use a fixed virtual coordinate space (`viewBox="0 0 800 120"`).
  * Explicitly call `renderChart()` upon tab activation (`switchTab('chart')`).
  * Implement touch and mouse scrubbing listeners directly on `#chartSvg` using relative bounding offsets (`clientX - rect.left`).

### Bug 4: The Hero Board Persistence Rule
* **Symptom:** Tapping the `Drill` tab displayed only a text box with no chessboard.
* **Root Cause:** The board was previously placed inside the `Board` tab container. Hiding that tab hid the board from other modes.
* **Lesson Learned:** The chessboard and vertical evaluation bar must remain **permanently visible at the top of the viewport** as the primary hero component. The tabs below the board control the panel context:
  * `🎓 Coach`: Move breakdown and alternative lines.
  * `📈 Chart`: Scrubbable win probability curve and notation record.
  * `🎯 Drill`: Blunder puzzle mode.
  * `📊 Review`: Accuracy cards and classification matrix.
* When entering `🎯 Drill` mode, the board automatically updates to `fen_before` (the position *before* the mistake), challenging the player to find the solution.

---

## 4. Chess.com Feature Suite Implementation

| Feature | Implementation Details |
|---|---|
| **Best Move Arrows** | Emerald green SVG arrow (`#arrowhead-best`) with endpoint retracted by 14px to prevent piece clipping. |
| **Played Move Arrows** | Color-coded based on classification: Red (`#ef4444`) for Blunder, Orange (`#f97316`) for Mistake, Yellow (`#eab308`) for Inaccuracy, Sky Blue (`#0ea5e9`) for Good. |
| **Vertical Eval Bar** | 24px wide bar aligned with board; animates White advantage from bottom using win probability; displays score (`+2.4`, `-M2`). |
| **CAPS2 Accuracy** | Computed via exponential loss: `100 * exp(-3.2 * avg_win_loss)` per player. |
| **Optimal Line Player** | Parses Stockfish `best_pv` into 4–5 steps with board animation, cyan arrows, step descriptions, and auto-play controls. |
| **Blunder Drill** | Filters player mistakes (`blunder`, `mistake`, `miss`); displays `fen_before`; reveals engine solution and arrow on demand. |

---

## 5. Dashboard Build & Deployment Routine

To update the dashboard with new games or coaching tips:
1. **Analyze Games:**
   ```bash
   uv run chess-coach analyze --limit 10
   ```
2. **Re-build Dashboard:**
   Run the production generator script:
   ```bash
   uv run python scratch/build_fixed_dashboard.py
   ```
3. **Validate JavaScript:**
   ```bash
   node -e "const fs=require('fs'); new Function(fs.readFileSync('index.html','utf8').match(/<script>([\s\S]*?)<\/script>/)[1]); console.log('Syntax OK');"
   ```
4. **Commit & Deploy:**
   ```bash
   git add index.html
   git commit -m "Update dashboard: [Description]"
   git push origin main
   ```
5. **Verify Live Deployment:**
   ```bash
   gh api repos/matthewveit2000/chess-coach/pages/builds/latest --jq .status
   ```
