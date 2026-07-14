from django import template

register = template.Library()

@register.simple_tag
def active_combo_ids(product, branch):
    """Return list of active combo IDs for the given product and branch."""
    return product.active_combo_ids(branch)

@register.filter(name='cloudinary_optimize')
def cloudinary_optimize(url, size=None):
    """
    Optimizes a Cloudinary image URL by adding f_auto, q_auto, and optional resizing.
    e.g. {{ image.url|cloudinary_optimize:"w_150,h_150" }}
    """
    if not url:
        return ""
    
    # If not a string (e.g. ImageFieldFile), get the url property
    if not isinstance(url, str):
        try:
            url = url.url
        except Exception:
            return ""
            
    if 'res.cloudinary.com' in url and '/upload/' in url:
        transform = "f_auto,q_auto"
        if size:
            transform += f",{size},c_fill"
        return url.replace('/upload/', f'/upload/{transform}/')
        
    return url
