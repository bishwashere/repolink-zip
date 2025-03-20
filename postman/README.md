# Postman Collection for GitHub Folder ZIP API

This folder contains a Postman collection that you can use to test the GitHub Folder ZIP API.

## Import Instructions

1. Open Postman
2. Click on "Import" in the top left
3. Select the file `github_folder_zip_api.postman_collection.json` from this folder
4. The collection will be imported into your Postman workspace

## Collection Variables

The collection uses the following variables that you can customize:

- **baseUrl**: The base URL of your API (default: `http://localhost:8000`)
- **custom_github_token**: Your personal GitHub token for accessing private repositories (if needed)

To update these variables:

1. Click on the collection name "GitHub Folder ZIP API" in Postman
2. Go to the "Variables" tab
3. Update the values as needed
4. Click "Save"

## Available Requests

The collection includes several pre-configured requests:

1. **Welcome Page**: Get the API welcome information
2. **Download Folder from Public Repo**: Download a specific folder from a public repository
3. **Download Entire Public Repo**: Download an entire public repository
4. **Download Folder with Custom Token**: Download from a private repository using a custom token
5. **Download Single Folder (Small)**: Download a small folder for quick testing
6. **Download UI Components**: Download UI components from a popular repository

## Usage Notes

- For production use, change the `baseUrl` variable to your deployed API URL
- When downloading private repositories, make sure to set the `custom_github_token` variable to a valid GitHub token
- The response will be either a direct file download or a JSON response with a download URL, depending on the R2 storage configuration
