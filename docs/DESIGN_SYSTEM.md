# ScholarPath design system ("ink on paper")

One calm, readable look for every page. Almost everything is set in
`.streamlit/config.toml` (Streamlit's own theme); `scholarpath/ui/style.py` adds a few CSS
rules, and `scholarpath/ui/common.py` holds the shared components.

## Tokens

| Token | Value | Used for |
|---|---|---|
| Paper (background) | `#FBFAF6` | Page |
| Sheet | `#FFFFFF` | Cards (`card_*` containers), charts |
| Input / table header | `#F0EEE7` | Fields, dataframe headers |
| Sidebar | `#F7F5EF` | Menu and dataset switch |
| Ink (text) | `#121118` | All text; captions are the same ink at 60 % |
| Primary | `#343A8C` | Primary buttons, links, selected tab/menu item, chart bars |
| Border | `#A8A397` | Cards, inputs |
| Focus ring | `#1D4ED8`, 3 px | Every focusable element |

Deadlines are plain text ("Deadline 8 Dec 2026 · 26 days left"); only a deadline within
7 days is bold ("**Closes in 3 days**"). Badges are used only for the verdict on Check my fit.

## Sequence and hierarchy
- One sequence: **Find scholarships → Review → Apply → Track the application**. Page titles,
  button labels and Back labels name the step ("Back to results", "View application").
- Menu: Find Scholarships, Saved, Applications, then a "More" group. On phone widths the
  three main links are repeated as a row at the top of the page (`mobile_nav` in `app.py`).
- One filled (primary) button per screen: Apply on provider site → Yes, add to Applications →
  View application → Save changes. Everything else is outlined or text-only.
- Secondary material sits behind a labelled control: *Filters and sorting*, *Table view and
  download*, *Original eligibility wording*, *Source and freshness*, *Update status*.
- No duplicate panels, metric rows or repeated instructions on the main pages.

## Type and spacing
- Headings: serif system stack (Iowan Old Style → Palatino → Georgia). Body: system sans.
  No web fonts are downloaded, so the app looks the same offline.
- Sizes: page title 2.1 rem (h1), section 1.45 rem (h2), card title 1.15 rem (h3), body 16 px.
- One `h1` per page; sections are `h2`; card titles are `h3`.
- Radius 0.5 rem everywhere. Content width capped at 70 rem.

## Components (all in `ui/common.py`)
- `page_header` - title, one-sentence purpose, dataset label. Same on every page.
- `card` + `card_summary` - scholarship, provider, where/level/funding, deadline line.
- `review_button` - opens Review and remembers which page Back returns to.
- `save` / `unsave` / `open_application` - the same actions with the same labels everywhere.
- `empty_state` - why a list is empty plus the next step.
- `flash` - toast after a committed write; errors stay on the page as `st.error`.
- `paginate` / `pager` - 10 results per page with Previous / Next.
- `run_page` - turns a database error into a message with a **Try again** button.

## Rules
- Native Streamlit widgets only. CSS may target `st-key-*` classes (from our own `key=`) and
  element states, never generated class names or test IDs.
- Untrusted text goes through `md_escape` / `badge_text`; no page renders HTML built from data.
- Meaning is never carried by colour alone.
- No hover animations; `prefers-reduced-motion` switches off Streamlit's own transitions.
