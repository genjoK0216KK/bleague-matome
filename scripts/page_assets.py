"""Shared head assets for full builds and standalone stats saves."""
import html
import re


def ga_snippet(ga_id):
    ga_id = html.escape(ga_id, quote=True)
    return (
        '<!-- AUTO:GA:START -->\n'
        f'<script async src="https://www.googletagmanager.com/gtag/js?id={ga_id}"></script>\n'
        '<script>window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}'
        f"gtag('js',new Date());gtag('config','{ga_id}');</script>\n"
        '<!-- AUTO:GA:END -->\n'
    )


def ensure_ga(text, ga_id):
    text = re.sub(r"<!-- AUTO:GA:START -->.*?<!-- AUTO:GA:END -->\n?", "", text, flags=re.DOTALL)
    if ga_id and "</head>" in text:
        text = text.replace("</head>", ga_snippet(ga_id) + "</head>", 1)
    return text


def ensure(text, ga_id):
    if 'href="design-system.css?v=1"' not in text:
        text = text.replace('</head>', '<link rel="stylesheet" href="design-system.css?v=1">\n</head>', 1)
    return ensure_ga(text, ga_id)
