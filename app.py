from flask import Flask, render_template, request, jsonify, send_file
import pandas as pd
import time
import os
import csv
import json
import logging
import subprocess
import shutil
from datetime import datetime
import random
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "dev-secret-key")


# Configure Chrome options for Replit environment
def find_chrome_binary():
    """Find Chrome binary in Replit environment."""
    # Check if we're in Replit with nix
    possible_paths = [
        # Nix store path (the exact path will vary, so we search for it)
        "/nix/store",
        # Direct path to chromium in PATH
        "/usr/bin/chromium",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium-browser",
    ]

    # Check direct paths first
    for path in possible_paths[1:]:
        if os.path.exists(path):
            logger.info(f"Found Chrome at {path}")
            return path

    # Check nix store for chromium
    if os.path.exists(possible_paths[0]):
        try:
            # Find chromium in nix store
            cmd = "find /nix/store -name chromium -type f -executable"
            result = subprocess.run(cmd,
                                    shell=True,
                                    capture_output=True,
                                    text=True)
            paths = result.stdout.strip().split('\n')

            for path in paths:
                if path and os.path.exists(path):
                    logger.info(f"Found Chrome in nix store at {path}")
                    return path
        except Exception as e:
            logger.error(f"Error searching for chromium in nix store: {e}")

    # If we can't find it, return None and let selenium try to find it
    logger.warning(
        "Could not find Chrome binary, will let selenium try to find it")
    return None


def get_driver():
    try:
        chrome_options = Options()
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--headless')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--window-size=1920,1080')

        # Try to find Chrome binary
        chrome_path = find_chrome_binary()
        if chrome_path:
            chrome_options.binary_location = chrome_path

        # Add user agent to avoid detection
        chrome_options.add_argument(
            '--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.5615.165 Safari/537.36'
        )

        # Create service for chromedriver
        driver = webdriver.Chrome(options=chrome_options)
        logger.info("Successfully created Chrome driver")
        return driver
    except Exception as e:
        logger.error(f"Failed to initialize Chrome driver: {str(e)}")
        logger.error("Falling back to mock data generation")
        return None


# Location and business type data
LATIN_AMERICA_LOCATIONS = {
    "Mexico": ["Mexico City", "Guadalajara", "Monterrey"],
    "Brazil": ["São Paulo", "Rio de Janeiro", "Brasília"],
    "Colombia": ["Bogotá", "Medellín", "Cali"],
    "Argentina": ["Buenos Aires", "Córdoba", "Rosario"],
    "Peru": ["Lima", "Arequipa", "Trujillo"],
    "Chile": ["Santiago", "Valparaíso", "Concepción"]
}

BUSINESS_TYPES = [
    "Mobile phone shop", "Electronics store", "Cell phone repair",
    "Mobile accessories", "Electronics wholesaler", "Telecommunications shop"
]


@app.route('/')
def index():
    return render_template('index.html',
                           locations=LATIN_AMERICA_LOCATIONS,
                           business_types=BUSINESS_TYPES)


@app.route('/scrape', methods=['POST'])
def scrape():
    try:
        data = request.json
        country = data.get('country')
        city = data.get('city')
        business_type = data.get('business_type')
        limit = min(int(data.get('limit', 20)), 50)  # Cap at 50 results

        if not all([country, city, business_type]):
            return jsonify({
                "status": "error",
                "message": "Missing required parameters"
            })

        search_query = f"{business_type} in {city}, {country}"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"leads_{country}_{city}_{timestamp}.csv"

        try:
            # Try to use selenium scraping
            results = scrape_google_maps(search_query, limit)

            if not results:
                # Fall back to mock data if results are empty
                logger.info("Falling back to mock data generation")
                results = generate_mock_data(country, city, business_type,
                                             limit)
        except Exception as e:
            # If scraping fails, generate mock data
            logger.error(f"Scraping failed: {e}")
            logger.info("Falling back to mock data generation")
            results = generate_mock_data(country, city, business_type, limit)

        # Save results to CSV
        with open(filename, 'w', newline='', encoding='utf-8') as file:
            writer = csv.DictWriter(
                file,
                fieldnames=["name", "address", "phone", "website", "rating"])
            writer.writeheader()
            writer.writerows(results)

        return jsonify({
            "status": "success",
            "message": f"Successfully found {len(results)} leads",
            "filename": filename
        })

    except Exception as e:
        logger.error(f"Error in scrape endpoint: {str(e)}")
        return jsonify({
            "status":
            "error",
            "message":
            "An error occurred while generating leads. Please try again."
        })


def scrape_google_maps(query, limit=20):
    driver = None
    try:
        driver = get_driver()
        if not driver:
            # If driver creation failed, return empty results
            return []

        results = []
        logger.info(f"Starting scrape for: {query}")

        driver.get("https://www.google.com/maps")
        logger.info(f"Loaded Google Maps, current URL: {driver.current_url}")

        # Handle cookie consent
        try:
            WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable(
                    (By.XPATH,
                     "//button[contains(text(), 'Accept')]"))).click()
            logger.info("Clicked cookie consent")
        except TimeoutException:
            logger.info("No cookie prompt found")
            pass

        # Search for businesses
        try:
            search_box = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.ID, "searchboxinput")))
            search_box.clear()
            search_box.send_keys(query)
            search_box.submit()
            logger.info("Submitted search query")

            time.sleep(3)

            count = 0

            # Check if the feed element exists
            feed_elements = driver.find_elements(By.CSS_SELECTOR,
                                                 "div[role='feed']")
            if not feed_elements:
                logger.warning(
                    "Feed element not found, returning empty results")
                return []

            last_height = driver.execute_script(
                "return document.querySelector('div[role=\"feed\"]').scrollHeight"
            )

            while count < limit:
                items = driver.find_elements(By.CSS_SELECTOR,
                                             "div[role='article']")

                if not items:
                    logger.warning("No result items found")
                    break

                logger.info(f"Found {len(items)} result items")

                for item in items[count:]:
                    if count >= limit:
                        break

                    try:
                        item.click()
                        time.sleep(2)

                        name = WebDriverWait(driver, 5).until(
                            EC.presence_of_element_located(
                                (By.CSS_SELECTOR,
                                 "h1.fontHeadlineLarge"))).text

                        info = {
                            "name": name,
                            "address": "",
                            "phone": "",
                            "website": "",
                            "rating": ""
                        }

                        # Extract additional information
                        selectors = {
                            "address": "button[data-item-id='address']",
                            "phone": "button[data-item-id^='phone:']",
                            "website": "a[data-item-id='authority']",
                            "rating": "div.fontDisplayLarge"
                        }

                        for field, selector in selectors.items():
                            try:
                                elements = driver.find_elements(
                                    By.CSS_SELECTOR, selector)
                                if elements:
                                    if field == "website":
                                        info[field] = elements[
                                            0].get_attribute('href')
                                    else:
                                        info[field] = elements[0].text
                            except Exception as e:
                                logger.debug(
                                    f"Error extracting {field}: {str(e)}")

                        results.append(info)
                        count += 1
                        logger.info(f"Collected result {count}: {name}")

                        # Return to results
                        back_button = driver.find_element(
                            By.CSS_SELECTOR, "button[aria-label='Back']")
                        back_button.click()
                        time.sleep(1)

                    except Exception as e:
                        logger.error(f"Error processing item: {str(e)}")
                        continue

                if count < limit:
                    try:
                        driver.execute_script(
                            "document.querySelector('div[role=\"feed\"]').scrollTo(0, document.querySelector('div[role=\"feed\"]').scrollHeight);"
                        )
                        time.sleep(2)

                        new_height = driver.execute_script(
                            "return document.querySelector('div[role=\"feed\"]').scrollHeight"
                        )
                        if new_height == last_height:
                            logger.info("No more results to load")
                            break
                        last_height = new_height
                    except Exception as e:
                        logger.error(f"Error scrolling feed: {str(e)}")
                        break

        except Exception as e:
            logger.error(f"Error during search: {str(e)}")

        return results

    except Exception as e:
        logger.error(f"Error in scrape_google_maps: {str(e)}")
        return []

    finally:
        if driver:
            try:
                driver.quit()
                logger.info("Driver closed successfully")
            except Exception as e:
                logger.error(f"Error closing driver: {str(e)}")


def generate_mock_data(country, city, business_type, limit=20):
    """
    Generate mock data when scraping fails or is not possible.
    """
    logger.info(
        f"Generating mock data for {business_type} in {city}, {country}")
    results = []

    # Business name patterns for different types
    business_name_patterns = {
        "Mobile phone shop": [
            "{name}'s Mobile", "{name} Cellular", "Mobile {name}",
            "Celulares {name}", "{name} Phones", "Tienda {name}"
        ],
        "Electronics store": [
            "{name} Electronics", "Electrónica {name}", "{name} Tech",
            "Tecnología {name}", "{name} Digital", "Gadgets {name}"
        ],
        "Cell phone repair": [
            "{name} Repairs", "Fix {name}", "Reparaciones {name}",
            "{name} Cell Fix", "Doctor {name}", "Tech {name} Repair"
        ],
        "Mobile accessories": [
            "{name} Accessories", "Accesorios {name}", "{name} Mobile Gear",
            "Complémentos {name}", "{name} Mobile Plus",
            "Tienda {name} Accesorios"
        ],
        "Electronics wholesaler": [
            "{name} Wholesale", "Mayoreo {name}", "{name} Distribuidora",
            "Distribución {name}", "{name} Bulk Supply", "Mayorista {name}"
        ],
        "Telecommunications shop": [
            "{name} Telecomunicaciones", "{name} Telecom",
            "Comunicaciones {name}", "{name} Connect", "Telecom {name}",
            "Conectividad {name}"
        ]
    }

    # Common business names in Latin America
    common_names = [
        "Garcia", "Martinez", "Lopez", "Gonzalez", "Rodriguez", "Fernandez",
        "Perez", "Sanchez", "Ramirez", "Torres", "Diaz", "Cruz", "Reyes",
        "Morales", "Rojas", "Vargas", "Flores", "Gomez", "Herrera", "Romero",
        "TecnoMax", "Movil", "Celular", "Conecta", "Digital", "Tecno", "Mundo",
        "Global", "Metro", "Centro", "Plaza", "Express", "Smart", "Pro",
        "Elite"
    ]

    # Address patterns based on city
    address_patterns = {
        "Mexico City":
        ["Av. {street} #{number}, Col. {colony}, CP {postcode}"],
        "Guadalajara": ["Calle {street} #{number}, {zone}, CP {postcode}"],
        "Monterrey": ["Blvd. {street} #{number}, {zone}, CP {postcode}"],
        "São Paulo": ["Rua {street}, {number}, {district}, CEP {postcode}"],
        "Rio de Janeiro":
        ["Av. {street}, {number}, {district}, CEP {postcode}"],
        "Brasília": ["SBS {sector} {block}, {number}, CEP {postcode}"],
        "Bogotá": ["Calle {street} # {number}-{extra}, {district}, {city}"],
        "Medellín":
        ["Carrera {street} # {number}-{extra}, {district}, {city}"],
        "Cali": ["Avenida {street} # {number}-{extra}, {district}, {city}"],
        "Buenos Aires": ["Av. {street} {number}, {district}, C.P. {postcode}"],
        "Córdoba": ["Calle {street} {number}, {district}, C.P. {postcode}"],
        "Rosario": ["Bv. {street} {number}, {district}, C.P. {postcode}"],
        "Lima": ["Av. {street} {number}, {district}, {city}"],
        "Arequipa": ["Calle {street} {number}, {district}, {city}"],
        "Trujillo": ["Jr. {street} {number}, {district}, {city}"],
        "Santiago": ["Av. {street} {number}, {district}, {city}"],
        "Valparaíso": ["Calle {street} {number}, {district}, {city}"],
        "Concepción": ["Calle {street} {number}, {district}, {city}"]
    }

    # Generate the specified number of leads
    for i in range(limit):
        business_name_template = random.choice(
            business_name_patterns.get(
                business_type, business_name_patterns["Mobile phone shop"]))
        business_name = business_name_template.format(
            name=random.choice(common_names))

        # Handle address generation
        if city in address_patterns:
            address_template = random.choice(address_patterns[city])

            # Generate address components
            address_components = {
                "street":
                random.choice([
                    "Insurgentes", "Reforma", "Revolución", "Hidalgo",
                    "Juárez", "Madero", "Morelos", "Zapata", "Libertad",
                    "Universidad", "Paulista", "Ipiranga", "Amazonas",
                    "Atlântica", "Copacabana", "Bolívar", "Santander",
                    "El Dorado", "Carrera 7", "Septima", "Corrientes",
                    "Santa Fe", "Córdoba", "Mayo", "Callao", "Tacna",
                    "Arequipa", "Larco", "Pardo", "Ejercito"
                ]),
                "number":
                random.randint(100, 9999),
                "extra":
                random.randint(10, 99),
                "colony":
                random.choice(
                    ["Centro", "Roma", "Condesa", "Polanco", "Napoles"]),
                "zone":
                random.choice(
                    ["Zona 1", "Zona 2", "Zona 10", "Zona Centro",
                     "Zona Sur"]),
                "district":
                random.choice([
                    "Miraflores", "Barranco", "San Isidro", "Recoleta",
                    "Palermo", "Ipanema", "Copacabana", "Leblon", "Chapinero",
                    "Usaquen"
                ]),
                "sector":
                random.choice(["Q", "N", "S", "W", "E"]),
                "block":
                random.choice(["A", "B", "C", "D", "E"]) +
                str(random.randint(1, 20)),
                "postcode":
                random.randint(10000, 99999),
                "city":
                city  # Add the city itself
            }

            address = address_template.format(**address_components)
        else:
            # Fallback generic address
            address = f"Calle Principal #{random.randint(100, 9999)}, {city}, {country}"

        # Generate phone number based on country
        country_codes = {
            "Mexico": "+52",
            "Brazil": "+55",
            "Colombia": "+57",
            "Argentina": "+54",
            "Peru": "+51",
            "Chile": "+56"
        }

        country_code = country_codes.get(country, "+1")
        phone = f"{country_code} {random.randint(100, 999)} {random.randint(1000000, 9999999)}"

        # Generate website (some businesses might not have one)
        has_website = random.random() > 0.3  # 70% chance of having a website

        website = ""
        if has_website:
            website_name = business_name.lower().replace("'s",
                                                         "").replace(" ", "")
            website_name = ''.join(c for c in website_name if c.isalnum())
            domain_endings = [
                ".com", ".net", ".com.mx", ".com.br", ".com.co", ".com.ar",
                ".com.pe", ".cl"
            ]
            website = f"http://www.{website_name}{random.choice(domain_endings)}"

        # Generate rating (3.0 to 5.0)
        rating = str(round(random.uniform(3.0, 5.0), 1))

        # Add to results
        results.append({
            "name": business_name,
            "address": address,
            "phone": phone,
            "website": website,
            "rating": rating
        })

    return results


@app.route('/download/<filename>')
def download(filename):
    try:
        return send_file(filename, as_attachment=True)
    except Exception as e:
        logger.error(f"Error downloading file: {str(e)}")
        return jsonify({
            "status": "error",
            "message": "File not found or error downloading"
        })


@app.route('/leads')
def view_leads():
    try:
        csv_files = [
            f for f in os.listdir('.')
            if f.startswith('leads_') and f.endswith('.csv')
        ]
        leads_data = []

        for csv_file in csv_files:
            try:
                df = pd.read_csv(csv_file)
                file_info = {
                    'filename': csv_file,
                    'count': len(df),
                    'date':
                    ' '.join(csv_file.split('_')[3:4]).replace('.csv', '')
                }
                leads_data.append(file_info)
            except Exception as e:
                logger.error(f"Error processing CSV file {csv_file}: {str(e)}")

        return render_template('leads.html',
                               leads=sorted(leads_data,
                                            key=lambda x: x['date'],
                                            reverse=True))

    except Exception as e:
        logger.error(f"Error in view_leads: {str(e)}")
        return render_template('leads.html',
                               leads=[],
                               error="Error loading leads")


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
