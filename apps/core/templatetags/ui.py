"""Template helpers for the design-system components in ``templates/components/``."""

from django import template
from django.template.loader import render_to_string
from django.utils.html import format_html

register = template.Library()


@register.simple_tag
def icon(name, extra_class=""):
    """Render an SVG sprite icon (the sprite is included once per layout)."""
    classes = f"ico {extra_class}".strip()
    return format_html(
        '<svg class="{}" aria-hidden="true"><use href="#i-{}"/></svg>', classes, name
    )


class ComponentNode(template.Node):
    """Render ``components/<name>.html`` with keyword arguments and the block body as ``body``."""

    def __init__(self, name, nodelist, kwargs):
        self.name = name
        self.nodelist = nodelist
        self.kwargs = kwargs

    def render(self, context):
        values = {key: expr.resolve(context) for key, expr in self.kwargs.items()}
        values["body"] = self.nodelist.render(context)
        values["request"] = context.get("request")
        values["csp_nonce"] = context.get("csp_nonce", "")
        return render_to_string(f"components/{self.name}.html", values)


def _block_component(name):
    def compile_tag(parser, token):
        bits = token.split_contents()[1:]
        kwargs = template.base.token_kwargs(bits, parser)
        if bits:
            raise template.TemplateSyntaxError(f"{{% {name} %}} accepts keyword arguments only")
        nodelist = parser.parse((f"end{name}",))
        parser.delete_first_token()
        return ComponentNode(name, nodelist, kwargs)

    register.tag(name, compile_tag)


for _name in ("card", "modal"):
    _block_component(_name)


@register.filter
def get_item(mapping, key):
    """``{{ row|get_item:column.key }}`` for data_table rows."""
    return mapping.get(key, "")


@register.filter
def nav_links(items):
    """Navigation entries that are links (drops group headings)."""
    return [item for item in items if not item.get("group")]


@register.filter
def elided_pages(page_obj):
    """Page numbers around the current page, with ``None`` marking a gap."""
    paginator = page_obj.paginator
    pages = paginator.get_elided_page_range(page_obj.number, on_each_side=1, on_ends=1)
    return [None if page == paginator.ELLIPSIS else page for page in pages]
