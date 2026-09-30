"""Rich Markdown rendered as native terminal cells, with clickable link spans."""
from functools import lru_cache
from rich.console import Console
from rich.markdown import Markdown
from rich.theme import Theme


@lru_cache(maxsize=32)
def render(text, width):
    console = Console(width=max(12, width), color_system='256', force_terminal=True,
                      theme=Theme({'markdown.h1': 'bold white', 'markdown.h2': 'bold white',
                                   'markdown.h3': 'bold white', 'markdown.code': 'bold cyan on grey19',
                                   'markdown.link': 'underline bright_blue',
                                   'markdown.link_url': 'underline bright_blue', 'markdown.item': 'bright_white'}))
    content = Markdown(text, code_theme='monokai', hyperlinks=True, justify='left')
    return console.render_lines(content, console.options.update(width=max(12, width)), pad=False)
