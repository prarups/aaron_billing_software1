from django import template

register = template.Library()

@register.simple_tag
def active_combo_ids(product, branch):
    """Return list of active combo IDs for the given product and branch."""
    return product.active_combo_ids(branch)
