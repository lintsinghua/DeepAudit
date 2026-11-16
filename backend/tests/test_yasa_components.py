"""Component units: the entries of one file side by side, with a guard table computed from the code."""
import sqlite3

from app.services.yasa_audit import components
from app.services.yasa_audit.assets import CallIndex

GOALS = "\n".join([
    "<?php",                                                    # 1
    "class GoalsApi {",                                         # 2
    "  public function getGoal($idSite, $id) {",                # 3
    "    Piwik::checkUserHasViewAccess($idSite);",              # 4
    "    return $this->model->get($idSite, $id);",              # 5
    "  }",                                                      # 6
    "  public function getGoals($idSite) {",                    # 7
    "    if ($this->cache->has($idSite)) { return $c; }",       # 8
    "    return $this->model->all($idSite);",                   # 9
    "  }",                                                      # 10
    "  public function deleteGoal($idSite, $id) {",             # 11
    "    $this->requireWrite($idSite);",                        # 12
    "    $this->model->delete($idSite, $id);",                  # 13
    "  }",                                                      # 14
    "  private function requireWrite($idSite) {",               # 15
    "    Piwik::checkUserHasWriteAccess($idSite);",             # 16
    "  }",                                                      # 17
    "  public function addGoal($idSite, $name) {",              # 18
    "    permissible($idSite, 'goal.add');",                    # 19
    "    $this->model->add($idSite, $name);",                   # 20
    "  }",                                                      # 21
    "}",                                                        # 22
])


def _project(tmp_path):
    (tmp_path / "Goals.php").write_text(GOALS)
    (tmp_path / ".codegraph").mkdir()
    con = sqlite3.connect(tmp_path / ".codegraph" / "codegraph.db")
    con.execute("create table nodes (id text primary key, kind text, name text, qualified_name text, "
                "file_path text, start_line int, end_line int)")
    con.execute("create table edges (source text, target text, kind text, line int)")
    rows = [("c", "class", "GoalsApi", "GoalsApi", "Goals.php", 2, 22)]
    for nid, name, s, e in (("m1", "getGoal", 3, 6), ("m2", "getGoals", 7, 10), ("m3", "deleteGoal", 11, 14),
                            ("m4", "requireWrite", 15, 17), ("m5", "addGoal", 18, 21)):
        rows.append((nid, "method", name, f"GoalsApi::{name}", "Goals.php", s, e))
    con.executemany("insert into nodes values (?,?,?,?,?,?,?)", rows)
    con.executemany("insert into edges values (?,?,?,?)", [("m3", "m4", "calls", 12)])
    con.commit()
    con.close()
    return CallIndex(tmp_path)


def _entries():
    return [{"id": f"E{i}", "method": "POST", "route": f"/api/Goals.{h}", "handler_file": "Goals.php",
             "handler": f"GoalsApi::{h}", "exposure": "authenticated"}
            for i, h in enumerate(("getGoal", "getGoals", "deleteGoal", "addGoal"), 1)]


def test_guard_table_shows_each_siblings_checks_including_same_file_helpers_and_project_guards(tmp_path):
    index = _project(tmp_path)
    # the project's own guard name comes from the access model's evidence, not from a list
    vocab = components.guard_vocabulary({"authorization": "routes call permissible(ctx, action)",
                                         "evidence": [{"quote": "Piwik::checkUserHasViewAccess($idSite);"},
                                                      {"quote": "$this->getModel()->load($id)"}]})
    assert "permissible" in vocab and "getmodel" not in vocab and "load" not in vocab
    ops = [{"file": "Goals.php", "line": 13, "op_class": "object_by_request_id"}]
    rows = {r["handler"].split("::")[-1]: r for r in (components.guard_row(index, e, ops, vocab) for e in _entries())}
    assert rows["getGoal"]["guards"] == ["checkUserHasViewAccess($idSite) L4"]
    assert rows["getGoals"]["guards"] == []  # the sibling without a check
    assert rows["deleteGoal"]["guards"] == ["requireWrite($idSite) L12",
                                            "checkUserHasWriteAccess($idSite) via requireWrite L16"]
    assert rows["deleteGoal"]["ops"] == ["object_by_request_id"]
    assert rows["addGoal"]["guards"] == ["permissible($idSite, 'goal.add') L19"]
    text = components.brief({"handler_file": "Goals.php", "handler": "4 entries"}, list(rows.values()))
    assert "checks: NONE in its code" in text and "1 of 4 rows make no check" in text


def test_component_units_group_siblings_by_role_and_keep_the_anonymous_surface_apart():
    rank = {"public": 0, "unknown": 1, "authenticated": 2, "privileged": 3, "operator": 4}

    def unit(f, h, exp, line):
        return {"kind": "entry", "handler_file": f, "handler": h, "handler_line": line, "exposure": exp,
                "entries": [{"id": h, "handler_file": f, "handler": h, "exposure": exp}], "operations": []}
    units = [unit("plugins/Goals/API.php", f"g{i}", "authenticated", 50 - i) for i in range(3)]
    units += [unit("plugins/Live/API.php", f"l{i}", "privileged", i) for i in range(2)]  # same role, other file
    units += [unit("plugins/Goals/API.php", "pub", "public", 1)]   # anonymous: its own entry unit
    units += [unit("plugins/Goals/Widget.php", f"w{i}", "authenticated", i) for i in range(3)]  # too few
    keep, comps = components.component_units(units, rank)
    assert len(comps) == 1 and comps[0]["files"] == ["plugins/Goals/API.php", "plugins/Live/API.php"]
    assert [m["handler"] for m in comps[0]["members"]] == ["g2", "g1", "g0", "l0", "l1"]  # by file, line order
    assert sorted(u["handler"] for u in keep) == ["pub", "w0", "w1", "w2"]


def test_a_generic_handler_is_one_component_of_its_resources(tmp_path):
    rank = {"public": 0, "unknown": 1, "authenticated": 2}
    units = [{"kind": "entry", "handler_file": "Controller.php", "handler": "renderWidget", "handler_line": 5,
              "generic": True, "exposure": "unknown", "entries": [{"id": f"E{i}", "route": f"/w/{i}"}],
              "operations": []} for i in range(10)]
    keep, comps = components.component_units(units, rank)
    assert not keep and len(comps) == 1 and len(comps[0]["entries"]) == 10
    rows = [{"id": f"E{i}", "request": f"GET /w/{i}", "handler": "renderWidget", "span": (5, 9), "guards": [],
             "ops": [], "exposure": "unknown"} for i in range(3)]
    text = components.brief(comps[0], rows)
    assert "serves 3 resources with the same code" in text and text.count("renderWidget") == 1


def test_large_groups_are_split_without_splitting_a_file_that_fits():
    rank = {"authenticated": 2}
    units = [{"kind": "entry", "handler_file": f"p{f}/API.php", "handler": f"m{f}-{i}", "handler_line": i,
              "exposure": "authenticated", "entries": [{"id": f"{f}-{i}"}], "operations": []}
             for f in range(3) for i in range(15)]  # 3 files x 15 entries, 40 rows per part
    _keep, comps = components.component_units(units, rank)
    assert [len(c["entries"]) for c in comps] == [30, 15] and comps[1]["files"] == ["p2/API.php"]


def test_operation_units_become_one_table_per_recipe_with_hubs_and_small_recipes_kept():
    rank = {"public": 0, "unknown": 1, "authenticated": 2, "privileged": 3}

    def op(fn, recipe, exposure="authenticated", unguarded=False, hub=False):
        site = {"file": "lib/x.php", "line": 10, "op_class": "raw_markup_output", "recipe": recipe,
                "code": f"echo $v; // {fn}", **({"guard_at": None} if unguarded else {})}
        return {"kind": "operation", "handler_file": "lib/x.php", "handler": fn, "span": (5, 20), "sites": [site],
                "entries": [{"id": f"E-{fn}"}], "exposure": exposure, "reach": "entry", "unguarded": unguarded,
                "hub": hub}
    ops = [op(f"r{i}", "raw-echo", unguarded=i == 3) for i in range(5)]
    ops += [op("q0", "query"), op("q1", "query")]          # too few for a table
    ops += [op("db", "raw-echo", hub=True)]                 # shared infrastructure: its own contract unit
    keep, tables = components.operation_tables(ops, rank)
    assert len(tables) == 1 and tables[0]["kind"] == "optable" and len(tables[0]["rows"]) == 5
    assert tables[0]["unguarded"] and tables[0]["recipe"] == "raw-echo"
    assert sorted(u["handler"] for u in keep) == ["db", "q0", "q1"]
    text = components.table_brief(tables[0], {"pattern": "echo", "guard": "escape\\(", "why": "templates"},
                                  "writes data into HTML")
    assert "the project's guard 'escape\\\\('" in text and "guard NOT on the way" in text and "L10: echo" in text
