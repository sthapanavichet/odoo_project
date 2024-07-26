
# Connect to the Odoo server
import xmlrpc.client
import pprint
import requests
from io import BytesIO
import base64
import json
import re
import html

url = '' # odoo server url and port
db = '' # odoo database name
username = '' # odoo email
password = '' # odoo password
# authenticating access to odoo database
common = xmlrpc.client.ServerProxy('{}/xmlrpc/2/common'.format(url))
uid = common.authenticate(db, username, password, {})
models = xmlrpc.client.ServerProxy('{}/xmlrpc/2/object'.format(url))

def main():
    stores = {
        # first store
        '': {  # shopify store name
                'api_token': '=',  # shopify admin access api key
                'api_key': '',
                'api_secret_key': '',
            },
        # second store
        '': {
                'api_token': '=',
                'api_key': '',
                'api_secret_key': '',
        }
        # possible for third store and so on.
    }
    
    PullInventory(stores)
    PushInventory(stores)

    

    

# 
def PullInventory(stores):
    '''
    Pulls the products from the Shopify stores and updates the products in Odoo.

    Args:
        stores (dict): A dictionary where the keys are store names and the values are dictionaries of API credentials for each store.

    Returns:
        None
    '''
    for store_name, api_creds in stores.items():
        print("Pulling products from ", store_name)
        domain = f'https://{store_name}.myshopify.com'
        endpoint = '/admin/api/2024-04/products.json'
        fields = '?fields=title,variants,status,images&limit=250'
        headers = {
            'Content-Type': 'application/json',
            'X-Shopify-Access-Token': api_creds['api_token'],
        }
        req_url = domain + endpoint + fields
        # retrieves all the products from the store
        response = requests.get(req_url, headers=headers)
        products = response.json()
        # if products exceed the limit of 250, retrieve the next page of products
        while 'next' in response.links.keys():
            next_url = response.links['next']['url']
            response = requests.get(next_url, headers=headers)
            products['products'].extend(response.json()['products'])
        # pprint.pprint(products)

        for product in products['products']:
            for variant in product['variants']:
                # Create the product template data if it doesn't exist, update if it does
                # check if product has variants, variants are stored as "{product_name} [{variant_name}]." in odoo
                if variant['title'] == 'Default Title':
                    name = product['title']
                else:
                    name = f"{product['title']} [{variant['title']}]."

                # search if product exists in odoo
                product_template_ids = models.execute_kw(db, uid, password, 'product.template', 'search', [[('name', '=', name)]])
                if len(product_template_ids) == 0:
                    print("Creating product: ", name, " in odoo")
                    # data we want to store
                    product_template_data = {
                        'name': name,
                        'list_price': variant['price'],
                        'weight': variant['weight'],
                        'type': 'product',
                        'default_code': variant['sku'],
                        'description': product['status'],
                    }

                    # Download image from shopfiy and add the image to the product template if it exists
                    if len(product['images']) > 0:
                        image_url = product['images'][0]['src']
                        response = requests.get(image_url)
                        image_data = base64.b64encode(response.content).decode('utf-8')
                        
                        product_template_data['image_1920'] = image_data
                    product_template_id = models.execute_kw(db, uid, password, 'product.template', 'create', [product_template_data])

                    # add additional images
                    for i in range(1, len(product['images'])):
                        image_url = product['images'][i]['src']
                        response = requests.get(image_url)
                        image_data = base64.b64encode(response.content).decode('utf-8')
                        image_data = {
                            'name': f"image_{i}",
                            'product_tmpl_id': product_template_id,
                            'image_1920': image_data,
                            }
                        models.execute_kw(db, uid, password, 'product.image', 'create', [image_data])

                    # Create the stock quant to represent the inventory
                    # inventory will be stored in the first internal location
                    internal_location_id = models.execute_kw(db, uid, password, 'stock.location', 'search', [[['usage', '=', 'internal']]], {'limit': 1})[0]
                    quant_data = {
                        'product_id': product_template_id,
                        'location_id': internal_location_id,
                        'quantity': variant['inventory_quantity'],
                    }
                    models.execute_kw(db, uid, password, 'stock.quant', 'create', [quant_data])
                else:
                    # search for product template in odoo and update its inventory
                    print("Updating product: ", name, " in odoo")
                    product_template_id = product_template_ids[0]
                    quant_id = models.execute_kw(db, uid, password, 'stock.quant', 'search', [[('product_id', '=', product_template_id)]])
                    quant = models.execute_kw(db, uid, password, 'stock.quant', 'read', [quant_id[0]])[0]

                    # check if inventory needs to be updated in odoo
                    if quant['quantity'] != variant['inventory_quantity']:
                        quant_data = {
                            'quantity': variant['inventory_quantity'],
                        }
                        models.execute_kw(db, uid, password, 'stock.quant', 'write', [[quant['id']], quant_data])
        print("Finished pulling products from ", store_name)
        print("")
    print("Finished pulling products from all stores\n\n")



def PushInventory(stores):
    '''
    Pushes the products to the Shopify stores from Odoo.

    Args:
        stores (dict): A dictionary where the keys are store names and the values are dictionaries of API credentials for each store.
        products (list): A list of dictionaries where each dictionary represents a product to be pushed to the stores.

    Returns:
        None
    '''
    
    for store_name, api_creds in stores.items():
        # retrieve products from shopify to compare with odoo
        headers = {
            'Content-Type': 'application/json',
            'X-Shopify-Access-Token': api_creds['api_token'],
        }
        domain = f'https://{store_name}.myshopify.com'
        endpoint = '/admin/api/2024-04/products.json'
        fields = '?fields=title,id,variants&limit=250'
        url = domain + endpoint + fields
        response = requests.get(url, headers=headers)
        products = response.json()
        # if products exceed the limit of 250, retrieve the next page of products
        while 'next' in response.links.keys():
            next_url = response.links['next']['url']
            response = requests.get(next_url, headers=headers)
            products['products'].extend(response.json()['products'])
        # create a dictionary of product names to their index in the products list
        # used to quickly find products in the products list
        product_names = {product['title']: i for i, product in enumerate(products['products'])}
        # retrieve the default location for inventory from shopify
        endpoint = '/admin/api/2024-04/locations.json'
        url = domain + endpoint
        response = requests.get(url, headers=headers)
        locations = response.json()['locations']
        # default location is the first location in the list, if 'shop location' exists, use that instead
        location_id = locations[0]['id']
        for location in locations:
            if location['name'] == 'Shop location':
                location_id = location['id']
                break
        
        # seting up urls for creating and updating products
        create_endpoint = '/admin/api/2024-04/products.json'
        create_url = domain + create_endpoint
        update_endpoint = '/admin/api/2024-04/inventory_levels/set.json'
        update_url = domain + update_endpoint

        # retrieve all products from odoo
        product_template_ids = models.execute_kw(db, uid, password, 'product.template', 'search', [[]])

        # products with variants that is already created in shopify
        # used specifically for product with variants, because they are stored as seperate products in odoo
        created_variants = []

        print("Pushing products to ", store_name)
        # go through each product in odoo and check if it exists in shopify
        for product_template_id in product_template_ids:
            product_template = models.execute_kw(db, uid, password, 'product.template', 'read', [product_template_id])[0]
            # ignore the standard delivery product stored internally
            if product_template['name'] == 'Standard delivery':
                continue
            
            # check if the product has variants and reformat the name accordingly
            if product_template['name'].endswith('.'):
                name = re.sub(r'\[.*?\]\.$', '', product_template['name']).strip()
            else:
                name = product_template['name']
            
            # ignore products that have already been pushed
            if name in created_variants:
                continue

            if name not in product_names.keys():
                print(f"creating product:'{name}'")
                variants = []
                # products with variants have a '.' at the end of their name
                if product_template['name'].endswith('.'):
                    # search for products that start with the same name in database
                    product_template_ids = models.execute_kw(db, uid, password, 'product.template', 'search', [[('name', 'like', name)]])
                    # add all variants of the product to the variants list
                    for product_template_id in product_template_ids:
                        # retrieve variant and inventory
                        product_template = models.execute_kw(db, uid, password, 'product.template', 'read', [product_template_id])[0]
                        quant_ids = models.execute_kw(db, uid, password, 'stock.quant', 'search', [[('product_id', '=', product_template['id'])]])
                        quant = models.execute_kw(db, uid, password, 'stock.quant', 'read', [quant_ids[0]])[0]
                        # remove the product name from the variant name
                        variant_name = re.search(r'\[(.*?)\]\.$', product_template['name']).group(1).strip()
                        variant = {
                            'option1': variant_name,
                            'price': product_template['list_price'],
                            'inventory_quantity': int(quant['quantity']) if quant else 0,
                            'inventory_management': 'shopify',
                            'sku': product_template['default_code'],
                            'weight': product_template['weight'],
                        }
                        variants.append(variant)
                # products without variants
                else:
                    # retrieve inventory
                    quant_ids = models.execute_kw(db, uid, password, 'stock.quant', 'search', [[('product_id', '=', product_template['id'])]])
                    quant = models.execute_kw(db, uid, password, 'stock.quant', 'read', [quant_ids[0]])[0]
                    variant = {
                        'option1': 'Default Title',
                        'price': product_template['list_price'],
                        'inventory_quantity': int(quant['quantity']) if quant else 0,
                        'inventory_management': 'shopify',
                        'sku': product_template['default_code'],
                        'weight': product_template['weight'],
                    }
                    variants.append(variant)

                # add images to the product, first image is the main image
                images = [
                    {
                        'attachment': product_template['image_1920'],
                    }
                ]
                # retrieve any additional images
                image_ids = models.execute_kw(db, uid, password, 'product.image', 'search', [[('product_tmpl_id', '=', product_template['id'])]])
                for image_id in image_ids:
                    image_data = models.execute_kw(db, uid, password, 'product.image', 'read', [image_id])[0]
                    images.append({
                        'attachment': image_data['image_1920'],
                    })

                data = {
                    'product': {
                        'title': name,
                        'status': re.sub('<[^<]+?>', '', product_template['description']),
                        'variants': variants,
                        'images': images,
                    }
                }
                # Make a POST request to the Shopify API to create a new product
                response = requests.post(create_url, headers=headers, data=json.dumps(data))
                # Check if the request was successful
                if response.status_code != 201:
                    print(f"Failed to create product '{name}' in Shopify: {response.text}")
                else:
                    print(f"Successfully created product '{name}' in Shopify with variants {variants}")
                    created_variants.append(name)
            # product exists in shopify, update the inventory
            else:
                print(f"updating product:'{name}'")
                # product with variants, update that specific variant
                if product_template['name'].endswith('.'):
                    for variant in products['products'][product_names[name]]['variants']:
                        if f"{name} [{variant['title']}]." == product_template['name']:
                            quant_id = models.execute_kw(db, uid, password, 'stock.quant', 'search', [[('product_id', '=', product_template['id'])]])[0]
                            quant = models.execute_kw(db, uid, password, 'stock.quant', 'read', [quant_id])[0]
                            data = {
                                'location_id': location_id,
                                'inventory_item_id': variant['inventory_item_id'],
                                'available': int(quant['quantity']),
                            }
                            break
                # product without variants
                else:
                    variant = products['products'][product_names[name]]['variants'][0]
                    quant_id = models.execute_kw(db, uid, password, 'stock.quant', 'search', [[('product_id', '=', product_template['id'])]])[0]
                    quant = models.execute_kw(db, uid, password, 'stock.quant', 'read', [quant_id])[0]
                    data = {
                        'location_id': location_id,
                        'inventory_item_id': variant['inventory_item_id'],
                        'available': int(quant['quantity']),
                    }
                
                # Make a POST request to the Shopify API to update the inventory
                response = requests.post(update_url, headers=headers, data=json.dumps(data))
                # Check if the request was successful
                if response.status_code != 200:
                    print(f"Failed to update inventory for '{name}' in Shopify: {response.text}")
                else:
                    print(f"Successfully updated inventory for '{name}' in Shopify to {quant['quantity']}")
        print("Finished pushing products to ", store_name)
        print("")
    print("Finished pushing products from all stores\n\n")

if __name__ == '__main__':
    main()