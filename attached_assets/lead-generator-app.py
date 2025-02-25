# app.py
from flask import Flask, render_template, request, jsonify, send_file
import pandas as pd
import time
import os
import csv
import random
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

app = Flask(__name__)

# Configure Chrome options for Replit environment
def get_driver():
    chrome_options = Options()
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--headless')
    driver = webdriver.Chrome(options=chrome_options)
    return driver

# List of Latin American countries and major cities
LATIN_AMERICA_LOCATIONS = {
    "Mexico": ["Mexico City", "Guadalajara", "Monterrey"],
    "Brazil": ["São Paulo", "Rio de Janeiro", "Brasília"],
    "Colombia": ["Bogotá", "Medellín", "Cali"],
    "Argentina": ["Buenos Aires", "Córdoba", "Rosario"],
    "Peru": ["Lima", "Arequipa", "Trujillo"],
    "Chile": ["Santiago", "Valparaíso", "Concepción"],
    # Add more countries and cities as needed
}

# Business types relevant to mobile device wholesale
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
    data = request.json
    country = data.get('country')
    city = data.get('city')
    business_type = data.get('business_type')
    limit = int(data.get('limit', 20))
    
    # Create search query
    search_query = f"{business_type} in {city}, {country}"
    
    # Generate a unique filename for this search
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"leads_{country}_{city}_{timestamp}.csv"
    
    try:
        results = scrape_google_maps(search_query, limit)
        
        # Save results to CSV
        with open(filename, 'w', newline='', encoding='utf-8') as file:
            writer = csv.DictWriter(file, fieldnames=["name", "address", "phone", "website", "rating"])
            writer.writeheader()
            writer.writerows(results)
        
        return jsonify({
            "status": "success", 
            "message": f"Found {len(results)} leads",
            "filename": filename
        })
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

def scrape_google_maps(query, limit=20):
    driver = get_driver()
    results = []
    
    try:
        # Navigate to Google Maps
        driver.get("https://www.google.com/maps")
        
        # Accept cookies if prompted (common in international versions)
        try:
            WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Accept')]"))
            ).click()
        except TimeoutException:
            pass  # No cookie prompt
            
        # Find search box and enter query
        search_box = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.ID, "searchboxinput"))
        )
        search_box.clear()
        search_box.send_keys(query)
        search_box.submit()
        
        # Wait for results to load
        time.sleep(3)
        
        # Start extracting data
        count = 0
        last_height = driver.execute_script("return document.querySelector('div[role=\"feed\"]').scrollHeight")
        
        while count < limit:
            # Find all result items
            items = driver.find_elements(By.CSS_SELECTOR, "div[role='article']")
            
            for item in items[count:]:
                if count >= limit:
                    break
                    
                try:
                    # Click on the item to load details
                    item.click()
                    time.sleep(2)
                    
                    # Extract business info
                    name = WebDriverWait(driver, 5).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "h1.fontHeadlineLarge"))
                    ).text
                    
                    # Get address, phone, website if available
                    address = ""
                    phone = ""
                    website = ""
                    rating = ""
                    
                    # Try to extract address
                    try:
                        address_elements = driver.find_elements(By.CSS_SELECTOR, "button[data-item-id='address']")
                        if address_elements:
                            address = address_elements[0].text
                    except:
                        pass
                    
                    # Try to extract phone
                    try:
                        phone_elements = driver.find_elements(By.CSS_SELECTOR, "button[data-item-id^='phone:']")
                        if phone_elements:
                            phone = phone_elements[0].text
                    except:
                        pass
                    
                    # Try to extract website
                    try:
                        website_elements = driver.find_elements(By.CSS_SELECTOR, "a[data-item-id='authority']")
                        if website_elements:
                            website = website_elements[0].get_attribute('href')
                    except:
                        pass
                    
                    # Try to extract rating
                    try:
                        rating_elements = driver.find_elements(By.CSS_SELECTOR, "div.fontDisplayLarge")
                        if rating_elements:
                            rating = rating_elements[0].text
                    except:
                        pass
                    
                    # Add to results
                    results.append({
                        "name": name,
                        "address": address,
                        "phone": phone,
                        "website": website,
                        "rating": rating
                    })
                    
                    count += 1
                    
                    # Go back to results
                    back_button = driver.find_element(By.CSS_SELECTOR, "button[aria-label='Back']")
                    back_button.click()
                    time.sleep(1)
                    
                except Exception as e:
                    print(f"Error extracting data: {e}")
                    continue
            
            # Scroll down to load more results if needed
            if count < limit:
                driver.execute_script("document.querySelector('div[role=\"feed\"]').scrollTo(0, document.querySelector('div[role=\"feed\"]').scrollHeight);")
                time.sleep(2)
                
                new_height = driver.execute_script("return document.querySelector('div[role=\"feed\"]').scrollHeight")
                if new_height == last_height:
                    # No more results
                    break
                last_height = new_height
        
        return results
        
    finally:
        driver.quit()

@app.route('/download/<filename>')
def download(filename):
    try:
        return send_file(filename, as_attachment=True)
    except:
        return jsonify({"status": "error", "message": "File not found"})

@app.route('/leads')
def view_leads():
    # Get all CSV files in the current directory
    csv_files = [f for f in os.listdir('.') if f.startswith('leads_') and f.endswith('.csv')]
    leads_data = []
    
    for csv_file in csv_files:
        try:
            df = pd.read_csv(csv_file)
            file_info = {
                'filename': csv_file,
                'count': len(df),
                'date': ' '.join(csv_file.split('_')[3:4]).replace('.csv', '')
            }
            leads_data.append(file_info)
        except:
            pass
    
    return render_template('leads.html', leads=leads_data)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
