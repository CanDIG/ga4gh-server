"""
An end to end test which tests:
- client cmd line parsing
- client operation
- client logging
- server cmd line parsing
- server operation
- simulated variantSet backend
- server logging
"""

import tests.end_to_end.server_test as server_test
import tests.end_to_end.client as client
import unittest

import candig.server.datarepo as datarepo


@unittest.skip("Disabled, client not used")
class TestGestalt(server_test.ServerTest):
    """
    An end-to-end test of the client and server
    """
    def testEndToEnd(self):
        # extract ids from a simulated data repo with the same config
        repo = datarepo.SimulatedDataRepository()
        dataset = repo.getDatasets()[0]
        datasetId = dataset.getId()
        variantSet = dataset.getVariantSets()[0]
        variantSetId = variantSet.getId()
        readGroupSet = dataset.getReadGroupSets()[0]
        readGroupId = readGroupSet.getReadGroups()[0].getId()
        referenceSet = repo.getReferenceSets()[0]
        referenceSetId = referenceSet.getId()
        referenceId = referenceSet.getReferences()[0].getId()
        variantAnnotationSetId = \
            variantSet.getVariantAnnotationSets()[0].getId()

        self.simulatedDatasetId = datasetId
        self.simulatedVariantSetId = variantSetId
        self.simulatedReadGroupId = readGroupId
        self.simulatedReferenceSetId = referenceSetId
        self.simulatedReferenceId = referenceId
        self.simulatedVariantAnnotationSetId = variantAnnotationSetId
        self.client = client.ClientForTesting(self.server.getUrl())
        self.runVariantsRequest()
        self.assertLogsWritten()
        self.runReadsRequest()
        self.runReferencesRequest()
        self.runVariantSetsRequestDatasetTwo()
        self.runVariantAnnotationsRequest()
        self.runGetVariantAnnotationSetsRequest()
        self.client.cleanup()

    def assertLogsWritten(self):
        serverOutLines = self.server.getOutLines()
        serverErrLines = self.server.getErrLines()
        clientOutLines = self.client.getOutLines()
        clientErrLines = self.client.getErrLines()

        # nothing should be written to server stdout
        self.assertEqual(
            [], serverOutLines,
            "Server stdout log not empty")

        # server stderr should log at least one response success
        responseFound = False
        for line in serverErrLines:
            if ' 200 ' in line:
                responseFound = True
                break
        self.assertTrue(
            responseFound,
            "No successful server response logged to stderr")

        # client stdout should not be empty
        self.assertNotEqual(
            [], clientOutLines,
            "Client stdout log is empty")

        # number of variants to expect
        expectedNumClientOutLines = 2
        self.assertEqual(len(clientOutLines), expectedNumClientOutLines)

        # client stderr should log at least one post
        requestFound = False
        for line in clientErrLines:
            if 'POST' in line:
                requestFound = True
                break
        self.assertTrue(
            requestFound,
            "No request logged from the client to stderr")

    def runVariantsRequest(self):
        self.runClientCmd(
            self.client,
            "variants-search",
            "-s 0 -e 2 -V {}".format(self.simulatedVariantSetId))

    def runVariantAnnotationsRequest(self):
        self.runClientCmd(
            self.client,
            "variantannotations-search",
            "--variantAnnotationSetId {} -s 0 -e 2".format(
                self.simulatedVariantAnnotationSetId))

    def runGetVariantAnnotationSetsRequest(self):
        self.runClientCmd(
            self.client,
            "variantannotationsets-get",
            "{}".format(self.simulatedVariantAnnotationSetId))

    def runReadsRequest(self):
        args = "--readGroupIds {} --referenceId {}".format(
            self.simulatedReadGroupId, self.simulatedReferenceId)
        self.runClientCmd(self.client, "reads-search", args)

    def runReferencesRequest(self):
        referenceSetId = self.simulatedReferenceSetId
        referenceId = self.simulatedReferenceId
        cmd = "referencesets-search"
        self.runClientCmd(self.client, cmd)
        cmd = "references-search"
        args = "--referenceSetId={}".format(referenceSetId)
        self.runClientCmd(self.client, cmd, args)
        cmd = "referencesets-get"
        args = "{}".format(referenceSetId)
        self.runClientCmd(self.client, cmd, args)
        cmd = "references-get"
        args = "{}".format(referenceId)
        self.runClientCmd(self.client, cmd, args)
        cmd = "references-list-bases"
        args = "{}".format(referenceId)
        self.runClientCmd(self.client, cmd, args)

    def runVariantSetsRequestDatasetTwo(self):
        cmd = "variantsets-search"
        args = "--datasetId {}".format(self.simulatedDatasetId)
        self.runClientCmd(self.client, cmd, args)
