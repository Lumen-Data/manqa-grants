# Manq'a Grants — Becas y Fondos

Scraper + dashboard that monitors grant opportunities relevant to Manq'a Sostenibles & Wayna.

- **Dashboard**: https://lumen-data.github.io/manqa-grants/
- **Schedule**: GitHub Actions cron every 2 days (`0 14 */2 * *` UTC)
- **Stack**: Python scraper + Claude API enrichment + static HTML dashboard (Alpine.js + Tailwind)

## TODO: Dismiss/Review Feature

Belen needs to mark grants as "reviewed/dismissed" so expired or irrelevant ones don't clutter the dashboard on return visits.

### Approach: localStorage (no backend needed)

Single file change: `docs/index.html`

1. **Alpine.js data** — add `dismissed: []` array + `showDismissed: false` toggle
2. **`init()`** — load dismissed URLs from `localStorage.getItem('mq-dismissed')`
3. **Helper methods**:
   - `dismiss(item)` — add URL to array, save to localStorage
   - `restore(item)` — remove URL from array, save to localStorage
   - `isDismissed(item)` — check if URL is in array
4. **Filter dismissed items** from all views by default:
   - `filtered` getter: hide dismissed unless `showDismissed` is true
   - `topPicks` getter: exclude dismissed
   - `urgentGrants` getter: exclude dismissed
5. **Dismiss button (X)** on each item:
   - Mobile cards: small X button, `@click.stop.prevent="dismiss(item)"`
   - Desktop table: X button in new last column, `@click.stop="dismiss(item)"`
   - `stop` modifier prevents opening the link
6. **"Descartadas" filter chip** next to Activas/Todas/Nuevas:
   - Shows count of dismissed items
   - When active, shows only dismissed items with a "Restaurar" (undo) button
7. **Restore button** — green undo icon replaces X when viewing dismissed items
