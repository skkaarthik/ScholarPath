# ScholarPath design system ("ink on paper")

One calm, readable look for every page. Almost everything is set in
`.streamlit/config.toml` (Streamlit's own theme, including the semantic badge and message
colours); `scholarpath/ui/style.py` adds a small amount of CSS, and
`scholarpath/ui/common.py` holds the shared components.

## Tokens

| Token | Value | Used for |
|---|---|---|
| Paper (background) | `#FBFAF6` | Page, phone menu bar |
| Sheet | `#FFFFFF` | Cards (`card_*` containers), metric tiles, charts |
| Fill | `#F0EEE7` | Inputs, table headers |
| Sidebar | `#F7F5EF` | Dataset switch |
| Ink | `#121118` | Text; secondary text `#4B4955` (8.4:1 on paper) |
| Primary | `#343A8C` | Primary buttons, links, highlighted menu entry, chart bars |
| Input border | `#857F72` | Inputs and outlined buttons: 3.8:1 on paper, 3.4:1 on the fill (WCAG 1.4.11) |
| Hairline | `#E2DED3` | Card borders, menu divider (decorative, not a control boundary) |
| Lavender | `#E9E8F7` | Highlighted menu entry (primary text on it: 8.2:1) |
| Focus ring | `#1D4ED8`, 3 px, 2 px offset | Every focusable element |
| Shadow | `0 1px 2px` at 5 % | Cards only; nothing heavier |

### Semantic states (theme colours, text at least 6:1 on its background)
| State | Colour | Examples |
|---|---|---|
| Success / open | green | "Open", "Result received", st.success |
| Needs attention soon | orange | "Closes in 3 days", "Example data" |
| Not confirmed | yellow | "Date not confirmed" |
| Information / selected | blue (the brand lavender) | "Saved", "Applied", "Rolling", st.info |
| Error | red | st.error, refused input |
| Neutral / finished | gray | "Closed", "No deadline published" |

The words always carry the meaning; colour only supports them.

## Type, width and spacing
- Headings: serif system stack (Iowan Old Style → Palatino → Georgia). Body: system sans.
  No web fonts or icons are downloaded, so the app looks the same offline.
- Sizes: h1 2.1 rem (1.75 rem on phones), h2 1.45 rem, h3 1.15 rem, body 16 px, menu 15 px
  (12 px labels in the phone bar). One `h1` per page; sections `h2`; card titles `h3`.
- Content width capped at 70 rem; long titles wrap (`overflow-wrap: anywhere`).
- Radius: 0.5 rem for cards, inputs and buttons; 0.75 rem for menu pills.
- Spacing comes from Streamlit's own gaps; cards hold one list row each, never a card in a card.

## Menu
- Entries, in order: **Find Scholarships, Saved, Applications, More** (Check my fit, Insights,
  Data & sources). Drawn in `app.py` from `st.page_link` and `st.popover`; Streamlit does the
  routing (`st.navigation(position="hidden")`).
- Each entry sits in a container keyed by us (`nav_find`, `nav_saved` ...). The highlighted entry's
  key ends in `_current`, and `style.py` draws it as a lavender pill with purple icon and label,
  a heavier label and a filled icon, so the state does not rely on colour alone.
- `common.menu_item()` decides what to highlight. Review is not in the menu, so it highlights the
  page it was opened from (the same page its Back button returns to); More pages highlight More.
- Targets: 44 px high, at least 44 px wide, 0.5 rem icon gap. Hover (pointer devices only) adds a
  primary tint at 8 %; transitions take 0.15 s and stop under "reduce motion".
- The More menu's key includes the open page, so choosing a page always draws a fresh, closed menu.
- Phones (≤ 40 rem): the same four entries become a fixed bar along the bottom edge, icon above
  label. There is no second copy of the links and nothing hides behind the sidebar arrow; the
  dataset switch is also on Data & sources.

## Hierarchy
- One sequence: **Find scholarships → Review → Apply → Track**. Titles, buttons and Back labels
  name the step ("Back to results", "Back to Saved", "View application").
- One filled (primary) button per state: Apply on provider site → Yes, add to Applications →
  View application → Save changes. Everything else is outlined or text-only.
- Secondary material sits behind a labelled control (Filters, Table view and CSV download,
  Original eligibility wording, Source and freshness, Update status, Technical details).
- Feedback stays where the action happened: the Saved badge on Review, the message inside an
  application entry, the error under the date field. No pop-up toasts (on phones they covered
  the buttons and the menu bar).

## Components (`ui/common.py`)
- `page_header`, `dataset_notice` - title, purpose, which dataset is showing.
- `card` + `card_summary` - scholarship, provider, where · level · funding, deadline badge.
- `deadline_state` / `deadline_line` / `deadline_plain` - one wording for six deadline states:
  closes today / within 7 days, open, closed, rolling, date not confirmed (the provider published
  wording without an exact date), no deadline published.
- `application_line`, `tracker_status` - status badge, outcome and submission date.
- `review_button`, `go_to`, `open_application` - navigation with a remembered Back target.
- `save` / `unsave` - success shown by the page itself; failures through `flash()`.
- `empty_state` - why a list is empty plus one next step.
- `paginate` / `pager` - 10 per page; `reset_widgets` clears widgets so the browser clears too.
- `safe_link_button` - outside links only for valid http(s) addresses, with the site named.
- `fmt_date` (8 Dec 2026), `fmt_ts` (8 Dec 2026, 10:00 UTC) - one date format everywhere.
- `run_page` - a database error becomes a calm message with **Try again**.

## Rules
- Native Streamlit widgets only. CSS starts from `st-key-*` classes (from our own `key=`),
  Streamlit's public element classes (`stMainBlockContainer`, `stButton` ...) or plain elements
  and states (`:focus-visible`, `aria-expanded`). Never generated class names or positions.
- Keep `<` out of the CSS comments in `style.py`: Streamlit's sanitiser drops a style block that
  looks like it contains a tag.
- Untrusted text goes through `md_escape` / `badge_text`; no page renders HTML built from data.
- Tables (`st.dataframe`) scroll inside their own box; the page never scrolls sideways.
