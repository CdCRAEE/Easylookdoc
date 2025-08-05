import requests

url = "https://easylookdoc-openai.openai.azure.com/openai/deployments/gpt-4o/chat/completions?api-version=2023-05-15"
headers = {
    "Content-Type": "application/json",
    "api-key": "DWzOqzIuJFKMRcfimbsydMe5nYelzbMeco4ODcPiknmqDdlwCVTFJQQJ99BGACYeBjFXJ3w3AAABACOGmisq"
}
data = {
    "messages": [
        {"role": "system", "content": "Sei un assistente utile."},
        {"role": "user", "content": "Ciao!"}
    ],
    "temperature": 0.7
}

response = requests.post(url, headers=headers, json=data)
print(response.status_code)
print(response.text)
