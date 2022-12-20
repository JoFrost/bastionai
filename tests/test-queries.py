#!/usr/bin/env python
# coding: utf-8


import polars as pl
import logging
import unittest
from bastionlab import Connection
from server import launch_server

logging.basicConfig(level=logging.INFO)


class TestingConnection(unittest.TestCase):
    def testingconnection(self):
        connection = Connection("localhost", 50056)
        client = connection.client
        self.assertNotEqual(client, None)
        connection.close()

    def testingdf(self):
        df = pl.read_csv("train.csv").limit(50)
        # The file train.csv is not included in the repository
        # But it is download from the execution of a jupyter notebook
        # for now
        connection = Connection("localhost", 50056)
        client = connection.client
        rdf = client.send_df(df)
        self.assertNotEqual(rdf, None)
        connection.close()

    def testingquery(self):
        df = pl.read_csv("train.csv").limit(50)
        connection = Connection("localhost", 50056)
        client = connection.client
        rdf = client.send_df(df)
        per_class_rates = (
            rdf.select([pl.col("Pclass"), pl.col("Survived")])
            .groupby(pl.col("Pclass"))
            .agg(pl.col("Survived").mean())
            .sort("Survived", reverse=True)
            .collect()
            .fetch()
        )
        self.assertNotEqual(per_class_rates, None)

    def testingquery2(self):
        df = pl.read_csv("train.csv").limit(50)
        connection = Connection("localhost", 50056)
        client = connection.client
        rdf = client.send_df(df)
        per_sex_rates = (
            rdf.select([pl.col("Sex"), pl.col("Survived")])
            .groupby(pl.col("Sex"))
            .agg(pl.col("Survived").mean())
            .sort("Survived", reverse=True)
            .collect()
            .fetch()
        )
        self.assertNotEqual(per_sex_rates, None)


def setUpModule():
    launch_server()


if __name__ == "__main__":
    unittest.main()
