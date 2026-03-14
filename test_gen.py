#!/usr/bin/env python3
import sys
sys.path.insert(0, r'c:\Users\hp\Desktop\awake\backend')

from app import generate_guaranteed_template

data = {
    'businessName': 'Test Co',
    'businessType': 'plumber',
    'location': 'London',
    'services': 'Emergency Repairs, Installation, Maintenance'
}

html = generate_guaranteed_template(data, 'test colors', 'Inter', 'test layout')

print(f'Generated HTML length: {len(html)}')
print(f'Contains DOCTYPE: {"<!DOCTYPE" in html}')
print(f'Contains html tag: {"<html" in html}')
print(f'Contains style tag: {"<style" in html}')

# Save to file for inspection
with open(r'c:\Users\hp\Desktop\awake\test_output.html', 'w', encoding='utf-8') as f:
    f.write(html)
    
print('Saved to test_output.html')
