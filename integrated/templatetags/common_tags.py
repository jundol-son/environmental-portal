from django import template

register = template.Library()

@register.simple_tag
def define(val=None):
  return val

@register.filter
def multiply(value, arg):
    try:
        return float(value) * float(arg)
    except (ValueError, TypeError):
        return 0