# EV Battery Swapping & Payment Management Platform

A web-based EV battery swapping management system built with **Python, Flask, SQLite, and Razorpay Checkout**. The project combines a battery swapping payment flow with an administrative dashboard for monitoring transactions and managing battery inventory.

## Project Overview

Electric vehicle battery swapping allows drivers to exchange a depleted battery for a charged one instead of waiting for the battery to recharge.

This project demonstrates the software side of a solar powered battery swapping station, including payment processing, transaction tracking, battery inventory, and station slot availability.

The goal is to connect the customer payment experience with the operational needs of a battery swapping station in one simple application.

## Key Features

### 1. EV Battery Swap Payment Flow
- Initiates a battery swap payment through Razorpay Checkout.
- Creates payment orders on the Flask backend.
- Uses a fixed swap amount of ₹50 in the current implementation.
- Verifies payment signatures on the server.
- Checks the payment's order ID, amount, currency, and captured status before updating the swap record.
- Stores swap and payment details in SQLite.

### 2. Admin Payment Dashboard
- Displays total swaps, paid swaps, pending swaps, and captured revenue.
- Shows transaction details, including swap ID, order ID, payment ID, amount, status, and creation time.
- Supports searching and filtering transactions.
- Provides a central view for monitoring payment activity.

### 3. Battery Inventory Management
- Stores individual battery records in SQLite.
- Tracks battery ID, charge percentage, slot number, status, and last-updated time.
- Supports adding batteries and updating their inventory details.
- Displays the total station slot count.
- Calculates empty slots, charged batteries, and batteries currently charging from database records.
- Prevents duplicate battery IDs and occupied slot assignments.


## Screenshots
<img width="679" height="557" alt="image" src="https://github.com/user-attachments/assets/1bd20ec9-4da1-435d-ab85-d6e8fee82820" />
<img width="626" height="356" alt="image" src="https://github.com/user-attachments/assets/2ff80e26-ab35-4308-83c8-b7abef5a1457" />


### Payment Dashboard
<img width="1320" height="644" alt="image" src="https://github.com/user-attachments/assets/a9364850-5bc2-4674-a5ab-81e4a002a67a" />


The admin dashboard provides a consolidated view of swap transactions, payment statuses, and captured revenue.

### Battery Inventory

<img width="1326" height="663" alt="image" src="https://github.com/user-attachments/assets/2e35524f-3ec3-4bc8-bfb0-fd74701fd549" />

The inventory page shows battery charge percentages, slot assignments, battery statuses, and station availability metrics.

## Technology Stack

| Technology | Purpose |
|---|---|
| Python | Application logic and backend processing |
| Flask | Web framework and API routes |
| SQLite | Persistent storage for swaps and battery inventory |
| Razorpay Checkout | Payment checkout integration |
| HTML and CSS | Web page structure and styling |
| JavaScript | Browser interactions and API requests |
| Jinja2 | Dynamic HTML rendering through Flask |

## System Architecture

The application follows a simple client-server architecture.

```text
Customer Web Page
       |
       v
Flask Backend
       |
       +------> Razorpay Checkout / Payment API
       |
       +------> Payment Verification
       |
       v
SQLite Database
       |
       +------> Swap Records
       |
       +------> Battery Inventory
       |
       v
Admin Dashboard
```

The Flask backend handles payment order creation, payment verification, transaction updates, and inventory operations. SQLite stores the application records, while the dashboard presents the relevant information to the administrator.

## Project Structure

```text
ev-swap-razorpay/
|
|-- app.py
|-- ev_swap.db              # Local database; not committed
|-- .env                    # Private credentials; not committed
|-- .gitignore
|-- templates/
|   |-- index.html
|   |-- dashboard.html
|   |-- battery_inventory.html|
|-- README.md
```

The actual file structure may differ slightly as the project evolves. The local database, credentials, and virtual environment should remain outside the public repository.

## Getting Started

### Prerequisites

- Python 3.9 or later
- Git
- A Razorpay account with API credentials suitable for development
- A web browser

### 1. Clone the repository

```bash
git clone https://github.com/sher122/ev-battery-swap-razorpay.git
cd ev-battery-swap-razorpay
```

### 2. Create a virtual environment

On Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, you can invoke the environment's Python directly:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 3. Install dependencies

```powershell
python -m pip install -r requirements.txt
```

If `requirements.txt` is not present in the repository yet, create it with the dependencies used by the application:

```text
Flask
razorpay
python-dotenv
```

### 4. Configure environment variables

Create a `.env` file in the project root:

```env
RAZORPAY_KEY_ID=your_razorpay_key_id
RAZORPAY_KEY_SECRET=your_razorpay_key_secret
```

Replace the example values with your own credentials. Never commit `.env` or expose secret values in screenshots, source code, or documentation.

### 5. Start the application

```powershell
python app.py
```

Open the following URLs in your browser:

| Page | URL |
|---|---|
| Customer payment page | http://127.0.0.1:5000/ |
| Payment admin dashboard | http://127.0.0.1:5000/dashboard |
| Battery inventory | http://127.0.0.1:5000/battery-inventory |

The SQLite tables are initialized by the application when its database initialization function runs.

## How the Payment Flow Works

1. The customer opens the battery swapping page.
2. The frontend requests a payment order from the Flask backend.
3. The backend creates a Razorpay order using the configured swap amount.
4. Razorpay Checkout handles the customer payment interaction.
5. The frontend sends the payment identifiers and signature to the backend.
6. The backend verifies the payment signature and checks the corresponding order.
7. The backend fetches the payment details and validates the order ID, amount, currency, and captured status.
8. The swap record is marked paid only after the required checks pass.
9. The admin dashboard displays the updated transaction information.

## API Endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/` | Displays the customer payment page |
| `POST` | `/api/create-order` | Creates a payment order and pending swap record |
| `POST` | `/api/verify-payment` | Verifies payment details and updates the swap |
| `GET` | `/dashboard` | Displays payment and swap statistics |
| `GET` | `/battery-inventory` | Displays battery records and inventory summaries |
| `POST` | `/api/batteries` | Adds a battery to inventory |
| `PATCH` | `/api/batteries/<battery_id>` | Updates battery charge, slot, and status |
| `GET` | `/api/swap/<swap_id>` | Retrieves a swap's status and payment information |
| `POST` | `/api/esp32/status` | Accepts a device status report |

The battery creation endpoint expects JSON containing a battery ID, integer charge percentage, optional slot number, and battery status. The update endpoint accepts the charge percentage, slot number, and status.

The device-status endpoint currently accepts `idle`, `ready`, and `busy` states. It logs the reported state; it does not directly control physical battery hardware.

## Battery Inventory Rules

The inventory supports the following battery statuses:

| Status | Meaning |
|---|---|
| `charged` | Battery is fully charged and ready |
| `charging` | Battery is currently charging |
| `in_use` | Battery is assigned for use |
| `maintenance` | Battery is unavailable for normal use |

The current implementation applies these rules:

- Battery IDs must be unique.
- Slot numbers must be within the configured station capacity.
- A slot cannot be assigned to multiple batteries.
- Charge percentage must be between 0 and 100.
- A battery marked `charged` must have a charge percentage of 100.
- A battery marked `charging` cannot already be at 100%.
- Empty slots are calculated from unoccupied slot assignments.

The current station is configured for 12 slots. This is an application configuration value, not a claim about a physically connected station.

## Security and Data Handling

The project includes several basic payment-security practices:

- Payment credentials are loaded through environment variables.
- The backend creates payment orders rather than trusting a price supplied by the browser.
- Payment signatures are verified on the server.
- The backend checks the payment against the expected order and amount.
- Payment details are fetched from Razorpay before a swap is marked paid.
- SQLite queries use parameterized statements for database operations.

**Important:** This is a development project, not a production-ready payment platform. Before production use, additional work would be needed around authentication and authorization, deployment security, monitoring, automated tests, database backups, and operational failure handling.

## Current Scope and Limitations

- The swap price is fixed at ₹50 in the current implementation.
- The application uses SQLite for local persistence.
- The station is initially configured for 12 slots.
- Battery records can be managed through the application, but charge levels are not automatically read from physical battery hardware by the inventory page.
- The ESP32 status endpoint accepts simulated or external status reports but does not actuate hardware.
- The application should be deployed behind a production-grade WSGI server before public production use.

## Future Improvements

- Integrate live battery telemetry from ESP32 hardware.
- Add station-wise inventory and configurable station capacity.
- Introduce user authentication and role-based administrator access.
- Add automated tests for payment verification, inventory validation, and failure cases.
- Add payment reconciliation reports and CSV export.
- Introduce inventory alerts for low charge, maintenance, and unavailable slots.
- Deploy the application to a secure hosting environment.

## What This Project Demonstrates

- Building a Flask application with REST-style endpoints.
- Integrating a payment gateway into a customer-facing workflow.
- Validating payment data on the backend.
- Designing and querying a relational database.
- Building an administrative dashboard with searchable transaction records.
- Implementing inventory and slot validation rules.
- Documenting application setup, API behavior, and technical limitations.

## Author

**Shrestha Sinha**

GitHub: [@sher122](https://github.com/sher122)


