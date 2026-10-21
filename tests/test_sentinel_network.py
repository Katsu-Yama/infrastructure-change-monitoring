import unittest

from scripts.sentinel import build_network, connected_components


OPTIONS = {'max_temporal_baseline_days': 36, 'max_perpendicular_baseline_m': 150,
           'max_bridge_temporal_days': 60, 'max_bridge_perpendicular_m': 300}


def record(date, baseline=0):
    return {'name': date, 'date': date, 'perpendicular_baseline_m': baseline}


class SentinelNetworkTests(unittest.TestCase):
    def test_bounded_redundant_bridges_connect_acquisition_gap(self):
        records = [record('2025-01-01', 0), record('2025-01-13', 10),
                   record('2025-02-25', 220), record('2025-03-09', 230)]
        scenes, pairs, network = build_network(records, OPTIONS)
        self.assertEqual(len(scenes), 4)
        self.assertEqual(len(connected_components(scenes, pairs)), 1)
        self.assertEqual(network['bridge_pair_count'], 3)
        self.assertEqual(network['excluded_disconnected_dates'], [])
        # There are two independent triangles across the gap, not one sole link.
        edges = {frozenset((p['first_date'], p['second_date'])) for p in pairs}
        self.assertTrue(all(frozenset(e) in edges for e in (
            ('2025-01-01', '2025-01-13'), ('2025-01-01', '2025-02-25'),
            ('2025-01-13', '2025-02-25'))))
        self.assertTrue(all(p['days'] <= 60 and p['perpendicular_baseline_m'] <= 300 for p in pairs))

    def test_unbridgeable_history_is_not_joined_to_latest_reference_frame(self):
        records = [record('2025-01-01'), record('2025-01-13'), record('2025-01-25'),
                   record('2025-10-01'), record('2025-10-13')]
        scenes, pairs, network = build_network(records, OPTIONS)
        self.assertEqual([r['date'] for r in scenes], ['2025-10-01', '2025-10-13'])
        self.assertEqual(len(pairs), 1)
        self.assertEqual(network['excluded_disconnected_dates'],
                         ['2025-01-01', '2025-01-13', '2025-01-25'])
        self.assertEqual(network['bridge_pair_count'], 0)


if __name__ == '__main__':
    unittest.main()
