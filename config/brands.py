BRANDS = {
    "ToyCorn": {
        "pcs_in_box": 16
    },
    "Kukuruzik": {
        "pcs_in_box": 20
    }
}


def get_brand(product):

    if product.startswith("ToyCorn"):
        return "ToyCorn"

    if product.startswith("Kukuruzik"):
        return "Kukuruzik"

    return None


def get_pcs_in_box(product):

    brand = get_brand(product)

    if not brand:
        return 20

    return BRANDS[brand]["pcs_in_box"]