from flask import Flask, render_template, request, jsonify, send_file
import pandas as pd
import time
import os
import csv
import logging
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
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
def get_driver():
    try:
        chrome_options = Options()
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--headless')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--window-size=1920,1080')

        # Add user agent to avoid detection
        chrome_options.add_argument('--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36')

        # Use WebDriver Manager to handle driver installation
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        return driver
    except Exception as e:
        logger.error(f"Failed to initialize Chrome driver: {str(e)}")
        raise

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
    "Mobile phone shop",
    "Electronics store",
    "Cell phone repair",
    "Mobile accessories",
    "Electronics wholesaler",
    "Telecommunications shop"
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
        
        results = scrape_google_maps(search_query, limit)
        
        # Save results to CSV
        with open(filename, 'w', newline='', encoding='utf-8') as file:
            writer = csv.DictWriter(file, fieldnames=["name", "address", "phone", "website", "rating"])
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
            "status": "error",
            "message": "An error occurred while scraping data"
        })

def scrape_google_maps(query, limit=20):
    driver = None
    try:
        driver = get_driver()
        results = []
        
        driver.get("https://www.google.com/maps")
        
        # Handle cookie consent
        try:
            WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Accept')]"))
            ).click()
        except TimeoutException:
            pass
            
        # Search for businesses
        search_box = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.ID, "searchboxinput"))
        )
        search_box.clear()
        search_box.send_keys(query)
        search_box.submit()
        
        time.sleep(3)
        
        count = 0
        last_height = driver.execute_script("return document.querySelector('div[role=\"feed\"]').scrollHeight")
        
        while count < limit:
            items = driver.find_elements(By.CSS_SELECTOR, "div[role='article']")
            
            for item in items[count:]:
                if count >= limit:
                    break
                    
                try:
                    item.click()
                    time.sleep(2)
                    
                    name = WebDriverWait(driver, 5).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "h1.fontHeadlineLarge"))
                    ).text
                    
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
                            elements = driver.find_elements(By.CSS_SELECTOR, selector)
                            if elements:
                                if field == "website":
                                    info[field] = elements[0].get_attribute('href')
                                else:
                                    info[field] = elements[0].text
                        except Exception as e:
                            logger.debug(f"Error extracting {field}: {str(e)}")
                    
                    results.append(info)
                    count += 1
                    
                    # Return to results
                    back_button = driver.find_element(By.CSS_SELECTOR, "button[aria-label='Back']")
                    back_button.click()
                    time.sleep(1)
                    
                except Exception as e:
                    logger.error(f"Error processing item: {str(e)}")
                    continue
            
            if count < limit:
                driver.execute_script("document.querySelector('div[role=\"feed\"]').scrollTo(0, document.querySelector('div[role=\"feed\"]').scrollHeight);")
                time.sleep(2)
                
                new_height = driver.execute_script("return document.querySelector('div[role=\"feed\"]').scrollHeight")
                if new_height == last_height:
                    break
                last_height = new_height
        
        return results
        
    except Exception as e:
        logger.error(f"Error in scrape_google_maps: {str(e)}")
        raise
    
    finally:
        if driver:
            driver.quit()

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
        csv_files = [f for f in os.listdir('.') if f.startswith('leads_') and f.endswith('.csv')]
        leads_data = []
        
        for csv_file in csv_files:
            try:
                df = pd.read_csv(csv_file)
                file_info = {
                    'filename': csv_file,
                    'count': len(df),
                    'date': datetime.strptime(csv_file.split('_')[3].replace('.csv', ''), '%Y%m%d').strftime('%Y-%m-%d')
                }
                leads_data.append(file_info)
            except Exception as e:
                logger.error(f"Error processing CSV file {csv_file}: {str(e)}")
        
        return render_template('leads.html', leads=sorted(leads_data, key=lambda x: x['date'], reverse=True))
        
    except Exception as e:
        logger.error(f"Error in view_leads: {str(e)}")
        return render_template('leads.html', leads=[], error="Error loading leads")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)