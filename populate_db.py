"""
populate_db.py

Populates shipment_database.db with shipment data drawn from three
source spreadsheets:

    data/shipping_data_0.csv   - one row per shipment (self-contained:
                                 already has product, quantity, origin,
                                 and destination).
    data/shipping_data_1.csv   - one row per individual product unit in a
                                 shipment (shipment_identifier, product).
                                 Quantity must be derived by counting how
                                 many rows share the same shipment and
                                 product.
    data/shipping_data_2.csv   - shipment metadata (shipment_identifier,
                                 origin_warehouse, destination_store) used
                                 to look up origin/destination for the
                                 shipments described in shipping_data_1.csv.

Database schema (shipment_database.db):

    product(id INTEGER PK, name TEXT UNIQUE NOT NULL)
    shipment(id INTEGER PK, product_id INTEGER FK -> product.id,
             quantity INTEGER, origin TEXT, destination TEXT)

Run:
    python populate_db.py
"""

from __future__ import annotations

import csv
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Dict, Tuple

DB_PATH = Path("shipment_database.db")
DATA_DIR = Path("data")
SELF_CONTAINED_CSV = DATA_DIR / "shipping_data_0.csv"
LINE_ITEMS_CSV = DATA_DIR / "shipping_data_1.csv"
SHIPMENT_INFO_CSV = DATA_DIR / "shipping_data_2.csv"


class ProductRepository:
    """
    Wraps all access to the `product` table.

    Keeps a local id cache so repeated lookups of the same product name
    (very common - the same product appears across many shipments) don't
    each cost a round trip to the database.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self._name_to_id: Dict[str, int] = {}

    def get_or_create_id(self, name: str) -> int:
        if name in self._name_to_id:
            return self._name_to_id[name]

        cursor = self._connection.cursor()
        cursor.execute("SELECT id FROM product WHERE name = ?", (name,))
        row = cursor.fetchone()

        if row is None:
            cursor.execute("INSERT INTO product (name) VALUES (?)", (name,))
            product_id = cursor.lastrowid
        else:
            product_id = row[0]

        self._name_to_id[name] = product_id
        return product_id


def insert_shipment(
    connection: sqlite3.Connection,
    product_id: int,
    quantity: int,
    origin: str,
    destination: str,
) -> None:
    connection.execute(
        """
        INSERT INTO shipment (product_id, quantity, origin, destination)
        VALUES (?, ?, ?, ?)
        """,
        (product_id, quantity, origin, destination),
    )


def load_self_contained_shipments(
    connection: sqlite3.Connection, products: ProductRepository, csv_path: Path
) -> None:
    """
    shipping_data_0.csv already has one row per shipment with everything
    we need (product, quantity, origin, destination), so each row maps
    directly onto one `shipment` row.
    """
    with csv_path.open(newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        for row in reader:
            product_id = products.get_or_create_id(row["product"])
            insert_shipment(
                connection,
                product_id=product_id,
                quantity=int(row["product_quantity"]),
                origin=row["origin_warehouse"],
                destination=row["destination_store"],
            )


def load_shipment_locations(csv_path: Path) -> Dict[str, Tuple[str, str]]:
    """
    shipping_data_2.csv holds one row per shipment with its origin and
    destination. Returns {shipment_identifier: (origin, destination)}.
    """
    locations: Dict[str, Tuple[str, str]] = {}
    with csv_path.open(newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        for row in reader:
            locations[row["shipment_identifier"]] = (
                row["origin_warehouse"],
                row["destination_store"],
            )
    return locations


def load_line_item_shipments(
    connection: sqlite3.Connection,
    products: ProductRepository,
    line_items_csv: Path,
    shipment_info_csv: Path,
) -> None:
    """
    shipping_data_1.csv has one row per individual unit of product shipped,
    so a shipment carrying 3 units of "pants" appears as 3 separate rows
    sharing the same shipment_identifier and product. We group rows by
    (shipment_identifier, product) and use the group size as the quantity,
    then look up each shipment's origin/destination from shipping_data_2.csv.
    """
    locations = load_shipment_locations(shipment_info_csv)

    with line_items_csv.open(newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        quantities = Counter(
            (row["shipment_identifier"], row["product"]) for row in reader
        )

    for (shipment_id, product_name), quantity in quantities.items():
        origin, destination = locations[shipment_id]
        product_id = products.get_or_create_id(product_name)
        insert_shipment(
            connection,
            product_id=product_id,
            quantity=quantity,
            origin=origin,
            destination=destination,
        )


def populate_database() -> None:
    connection = sqlite3.connect(DB_PATH)
    try:
        products = ProductRepository(connection)
        load_self_contained_shipments(connection, products, SELF_CONTAINED_CSV)
        load_line_item_shipments(
            connection, products, LINE_ITEMS_CSV, SHIPMENT_INFO_CSV
        )
        connection.commit()
    finally:
        connection.close()


if __name__ == "__main__":
    populate_database()
