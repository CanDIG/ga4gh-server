"""
Unit tests for sequence annotation Feature and FeatureSet objects.
This is used for all tests that can be performed in isolation
from input data.
"""

import unittest

import candig.server.datamodel.sequence_annotations as sequence_annotations
import candig.server.datamodel.datasets as datasets


class TestAbstractFeatureSet(unittest.TestCase):
    """
    Unit tests for the abstract feature set.
    """
    def setUp(self):
        self._featureSetName = "testFeatureSet"
        self._dataset = datasets.Dataset("test_ds")
        self._featureSet = sequence_annotations.AbstractFeatureSet(
            self._dataset, self._featureSetName)

    def testGetFeatureIdFailsWithNullInput(self):
        self.assertEqual("",
                         self._featureSet.getCompoundIdForFeatureId(None))
