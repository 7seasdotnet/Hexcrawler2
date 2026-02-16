from hexcrawler.content.io import load_world_json
from hexcrawler.cli.pygame_viewer import _build_parser


def test_viewer_default_map_has_broad_explorable_topology() -> None:
    parser = _build_parser()
    args = parser.parse_args([])
    world = load_world_json(args.map_path)

    assert len(world.hexes) >= 100
