"""Shared admin UI snippets."""


def workflow_steps(active: int) -> str:
    """Render a 3-step indicator: Topics -> Pipeline -> Templates.

    `active` is 1, 2, or 3 matching the current page.
    """
    steps = [
        (1, "Topics",    "/admin/pipeline/topics"),
        (2, "Pipeline",  "/admin/pipeline/"),
        (3, "Templates", "/admin/templates"),
    ]
    parts = []
    for n, label, href in steps:
        if n == active:
            parts.append(
                f'<span style="background:#e8a849;color:#0f1419;padding:4px 12px;'
                f'border-radius:3px;font-weight:600">{n} \u00b7 {label}</span>'
            )
        else:
            parts.append(
                f'<a href="{href}" style="color:#b8bfc9;background:#1d242e;'
                f'border:1px solid #2a323d;padding:4px 12px;border-radius:3px;'
                f'text-decoration:none">{n} \u00b7 {label}</a>'
            )
        if n < 3:
            parts.append('<span style="color:#5a6472">\u2192</span>')

    return (
        '<div style="display:flex;align-items:center;gap:8px;margin:12px 0 10px;'
        "font-size:11px;font-family:'IBM Plex Mono',ui-monospace,monospace;"
        'letter-spacing:0.1em;text-transform:uppercase;flex-wrap:wrap">'
        + "".join(parts)
        + "</div>"
    )
