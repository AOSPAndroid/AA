import { applySourcePlanDetails } from "./map-plan-details.js?v=4";
// Locations confirmed by the office owner. Coordinates follow each individual floor plan.
const amenities = {
  "2": [
    {
      "id": "toilets-left-upper",
      "name": "Toilets",
      "kind": "wc",
      "anchor": [
        215,
        777
      ],
      "points": [
        [
          203,
          765
        ],
        [
          227,
          765
        ],
        [
          227,
          789
        ],
        [
          203,
          789
        ]
      ]
    },
    {
      "id": "toilets-left-lower",
      "name": "Toilets",
      "kind": "wc",
      "anchor": [
        164,
        1048
      ],
      "points": [
        [
          152,
          1036
        ],
        [
          176,
          1036
        ],
        [
          176,
          1060
        ],
        [
          152,
          1060
        ]
      ]
    },
    {
      "id": "toilets-right",
      "name": "Toilets",
      "kind": "wc",
      "anchor": [
        1378,
        855
      ],
      "points": [
        [
          1366,
          843
        ],
        [
          1390,
          843
        ],
        [
          1390,
          867
        ],
        [
          1366,
          867
        ]
      ]
    },
    {
      "id": "print-stationery",
      "name": "Print & stationery",
      "kind": "print",
      "anchor": [
        1304,
        953
      ],
      "points": [
        [
          1292,
          941
        ],
        [
          1316,
          941
        ],
        [
          1316,
          965
        ],
        [
          1292,
          965
        ]
      ]
    },
    {
      "id": "kitchen-coffee",
      "name": "Kitchen & coffee",
      "kind": "kitchen",
      "anchor": [
        863,
        710
      ],
      "points": [
        [
          851,
          698
        ],
        [
          875,
          698
        ],
        [
          875,
          722
        ],
        [
          851,
          722
        ]
      ]
    }
  ],
  "3": [
    {
      "id": "toilets-left-upper",
      "name": "Toilets",
      "kind": "wc",
      "anchor": [
        147,
        552
      ],
      "points": [
        [
          135,
          540
        ],
        [
          159,
          540
        ],
        [
          159,
          564
        ],
        [
          135,
          564
        ]
      ]
    },
    {
      "id": "toilets-left-lower",
      "name": "Toilets",
      "kind": "wc",
      "anchor": [
        78,
        840
      ],
      "points": [
        [
          66,
          828
        ],
        [
          90,
          828
        ],
        [
          90,
          852
        ],
        [
          66,
          852
        ]
      ]
    },
    {
      "id": "toilets-right",
      "name": "Toilets",
      "kind": "wc",
      "anchor": [
        1410,
        646
      ],
      "points": [
        [
          1398,
          634
        ],
        [
          1422,
          634
        ],
        [
          1422,
          658
        ],
        [
          1398,
          658
        ]
      ]
    },
    {
      "id": "print-stationery",
      "name": "Print & stationery",
      "kind": "print",
      "anchor": [
        1347,
        748
      ],
      "points": [
        [
          1335,
          736
        ],
        [
          1359,
          736
        ],
        [
          1359,
          760
        ],
        [
          1335,
          760
        ]
      ]
    },
    {
      "id": "kitchen-coffee",
      "name": "Kitchen & coffee",
      "kind": "kitchen",
      "anchor": [
        866,
        463
      ],
      "points": [
        [
          854,
          451
        ],
        [
          878,
          451
        ],
        [
          878,
          475
        ],
        [
          854,
          475
        ]
      ]
    }
  ],
  "4": [
    {
      "id": "toilets-left-upper",
      "name": "Toilets",
      "kind": "wc",
      "anchor": [
        147,
        550
      ],
      "points": [
        [
          135,
          538
        ],
        [
          159,
          538
        ],
        [
          159,
          562
        ],
        [
          135,
          562
        ]
      ]
    },
    {
      "id": "toilets-left-lower",
      "name": "Toilets",
      "kind": "wc",
      "anchor": [
        78,
        832
      ],
      "points": [
        [
          66,
          820
        ],
        [
          90,
          820
        ],
        [
          90,
          844
        ],
        [
          66,
          844
        ]
      ]
    },
    {
      "id": "toilets-right",
      "name": "Toilets",
      "kind": "wc",
      "anchor": [
        1410,
        644
      ],
      "points": [
        [
          1398,
          632
        ],
        [
          1422,
          632
        ],
        [
          1422,
          656
        ],
        [
          1398,
          656
        ]
      ]
    },
    {
      "id": "print-stationery",
      "name": "Print & stationery",
      "kind": "print",
      "anchor": [
        1347,
        746
      ],
      "points": [
        [
          1335,
          734
        ],
        [
          1359,
          734
        ],
        [
          1359,
          758
        ],
        [
          1335,
          758
        ]
      ]
    },
    {
      "id": "kitchen-coffee",
      "name": "Kitchen & coffee",
      "kind": "kitchen",
      "anchor": [
        866,
        461
      ],
      "points": [
        [
          854,
          449
        ],
        [
          878,
          449
        ],
        [
          878,
          473
        ],
        [
          854,
          473
        ]
      ]
    }
  ],
  "5": [
    {
      "id": "toilets-left-upper",
      "name": "Toilets",
      "kind": "wc",
      "anchor": [
        147,
        550
      ],
      "points": [
        [
          135,
          538
        ],
        [
          159,
          538
        ],
        [
          159,
          562
        ],
        [
          135,
          562
        ]
      ]
    },
    {
      "id": "toilets-left-lower",
      "name": "Toilets",
      "kind": "wc",
      "anchor": [
        78,
        832
      ],
      "points": [
        [
          66,
          820
        ],
        [
          90,
          820
        ],
        [
          90,
          844
        ],
        [
          66,
          844
        ]
      ]
    },
    {
      "id": "toilets-right",
      "name": "Toilets",
      "kind": "wc",
      "anchor": [
        1410,
        644
      ],
      "points": [
        [
          1398,
          632
        ],
        [
          1422,
          632
        ],
        [
          1422,
          656
        ],
        [
          1398,
          656
        ]
      ]
    },
    {
      "id": "print-stationery",
      "name": "Print & stationery",
      "kind": "print",
      "anchor": [
        1347,
        746
      ],
      "points": [
        [
          1335,
          734
        ],
        [
          1359,
          734
        ],
        [
          1359,
          758
        ],
        [
          1335,
          758
        ]
      ]
    },
    {
      "id": "kitchen-coffee",
      "name": "Kitchen & coffee",
      "kind": "kitchen",
      "anchor": [
        866,
        461
      ],
      "points": [
        [
          854,
          449
        ],
        [
          878,
          449
        ],
        [
          878,
          473
        ],
        [
          854,
          473
        ]
      ]
    }
  ],
  "6": [
    {
      "id": "toilets-left-upper",
      "name": "Toilets",
      "kind": "wc",
      "anchor": [
        147,
        545
      ],
      "points": [
        [
          135,
          533
        ],
        [
          159,
          533
        ],
        [
          159,
          557
        ],
        [
          135,
          557
        ]
      ]
    },
    {
      "id": "toilets-left-lower",
      "name": "Toilets",
      "kind": "wc",
      "anchor": [
        78,
        825
      ],
      "points": [
        [
          66,
          813
        ],
        [
          90,
          813
        ],
        [
          90,
          837
        ],
        [
          66,
          837
        ]
      ]
    },
    {
      "id": "toilets-right",
      "name": "Toilets",
      "kind": "wc",
      "anchor": [
        1410,
        637
      ],
      "points": [
        [
          1398,
          625
        ],
        [
          1422,
          625
        ],
        [
          1422,
          649
        ],
        [
          1398,
          649
        ]
      ]
    },
    {
      "id": "print-stationery",
      "name": "Print & stationery",
      "kind": "print",
      "anchor": [
        1347,
        739
      ],
      "points": [
        [
          1335,
          727
        ],
        [
          1359,
          727
        ],
        [
          1359,
          751
        ],
        [
          1335,
          751
        ]
      ]
    },
    {
      "id": "kitchen-coffee",
      "name": "Kitchen & coffee",
      "kind": "kitchen",
      "anchor": [
        866,
        453
      ],
      "points": [
        [
          854,
          441
        ],
        [
          878,
          441
        ],
        [
          878,
          465
        ],
        [
          854,
          465
        ]
      ]
    }
  ],
  "7": [
    {
      "id": "toilets-left-upper",
      "name": "Toilets",
      "kind": "wc",
      "anchor": [
        147,
        550
      ],
      "points": [
        [
          135,
          538
        ],
        [
          159,
          538
        ],
        [
          159,
          562
        ],
        [
          135,
          562
        ]
      ]
    },
    {
      "id": "toilets-left-lower",
      "name": "Toilets",
      "kind": "wc",
      "anchor": [
        78,
        832
      ],
      "points": [
        [
          66,
          820
        ],
        [
          90,
          820
        ],
        [
          90,
          844
        ],
        [
          66,
          844
        ]
      ]
    },
    {
      "id": "toilets-right",
      "name": "Toilets",
      "kind": "wc",
      "anchor": [
        1410,
        644
      ],
      "points": [
        [
          1398,
          632
        ],
        [
          1422,
          632
        ],
        [
          1422,
          656
        ],
        [
          1398,
          656
        ]
      ]
    },
    {
      "id": "print-stationery",
      "name": "Print & stationery",
      "kind": "print",
      "anchor": [
        1347,
        746
      ],
      "points": [
        [
          1335,
          734
        ],
        [
          1359,
          734
        ],
        [
          1359,
          758
        ],
        [
          1335,
          758
        ]
      ]
    },
    {
      "id": "kitchen-coffee",
      "name": "Kitchen & coffee",
      "kind": "kitchen",
      "anchor": [
        866,
        461
      ],
      "points": [
        [
          854,
          449
        ],
        [
          878,
          449
        ],
        [
          878,
          473
        ],
        [
          854,
          473
        ]
      ]
    }
  ]
};

// Shared elevator bank, registered against the same two architectural corners on each plan.
const elevatorBank = {
  name: "Elevators", kind: "lift", id: "elevator-bank",
  points: [[552.01, 900], [730.3, 738.88], [774.15, 784.64], [598.73, 939.09]],
  anchor: [663.5593220338983, 810.3813559322034],
};
// Stairwells confirmed by the office owner; outlines follow the Level 2 treads.
const stairwells = [
  { id: "stairs-left", name: "Stairs · left", kind: "stairs",
    anchor: [138, 922], points: [[103.13, 884.74], [173.74, 884.74], [173.74, 955.35], [103.13, 955.35]] },
  { id: "stairs-centre", name: "Stairs · centre", kind: "stairs",
    anchor: [807, 940], points: [[766, 904.23], [848, 904.23], [848, 974], [766, 974]] },
  { id: "stairs-right", name: "Stairs · right", kind: "stairs",
    anchor: [1480, 775], points: [[1405, 750], [1463, 697], [1556, 800], [1498, 853]] },
];
const registrations = {
  2: [[92.16, 850.3], [739.52, 449.53]],
  3: [[13.85, 627.18], [723.48, 188]],
  4: [[13.85, 627.18], [723.48, 188]],
  5: [[13.85, 627.18], [723.48, 188]],
  6: [[13.85, 627.18], [723.48, 188]],
  7: [[13.85, 628.78], [723.1, 189.6]],
};
// Lower floors use their own source-plan labels; their layout differs from office floors.
const lowerFloorAmenities = {"-1":[{"id":"lift-main","name":"Elevators","kind":"lift","anchor":[754.9,939.3],"points":[[745.9,930.3],[763.9,930.3],[763.9,948.3],[745.9,948.3]]},{"id":"lift-annex","name":"Elevator","kind":"lift","anchor":[568.4,528.4],"points":[[559.4,519.4],[577.4,519.4],[577.4,537.4],[559.4,537.4]]},{"id":"lift-west","name":"Elevator","kind":"lift","anchor":[371.1,663.0],"points":[[362.1,654.0],[380.1,654.0],[380.1,672.0],[362.1,672.0]]},{"id":"stairs-north","name":"Stairs","kind":"stairs","anchor":[1007.6,103.9],"points":[[998.6,94.9],[1016.6,94.9],[1016.6,112.9],[998.6,112.9]]},{"id":"stairs-annex","name":"Stairs","kind":"stairs","anchor":[646.2,434.8],"points":[[637.2,425.8],[655.2,425.8],[655.2,443.8],[637.2,443.8]]},{"id":"stairs-west","name":"Stairs","kind":"stairs","anchor":[413.6,620.6],"points":[[404.6,611.6],[422.6,611.6],[422.6,629.6],[404.6,629.6]]},{"id":"stairs-east","name":"Stairs","kind":"stairs","anchor":[1331.2,922.4],"points":[[1322.2,913.4],[1340.2,913.4],[1340.2,931.4],[1322.2,931.4]]},{"id":"stairs-inner","name":"Stairs","kind":"stairs","anchor":[927.0,953.5],"points":[[918.0,944.5],[936.0,944.5],[936.0,962.5],[918.0,962.5]]},{"id":"stairs-centre","name":"Stairs","kind":"stairs","anchor":[775.1,1038.5],"points":[[766.1,1029.5],[784.1,1029.5],[784.1,1047.5],[766.1,1047.5]]},{"id":"stairs-south","name":"Stairs","kind":"stairs","anchor":[1160.0,1126.3],"points":[[1151.0,1117.3],[1169.0,1117.3],[1169.0,1135.3],[1151.0,1135.3]]},{"id":"employee-restaurant","name":"Employee restaurant","kind":"room","anchor":[918,605],"points":[[909,596],[927,596],[927,614],[909,614]]}],"0":[{"id":"lift-main","name":"Elevators","kind":"lift","anchor":[754.1,940.4],"points":[[745.1,931.4],[763.1,931.4],[763.1,949.4],[745.1,949.4]]},{"id":"lift-annex","name":"Elevator","kind":"lift","anchor":[564.2,531.4],"points":[[555.2,522.4],[573.2,522.4],[573.2,540.4],[555.2,540.4]]},{"id":"lift-west","name":"Elevator","kind":"lift","anchor":[373.9,663.4],"points":[[364.9,654.4],[382.9,654.4],[382.9,672.4],[364.9,672.4]]},{"id":"stairs-annex","name":"Stairs","kind":"stairs","anchor":[610.1,402.8],"points":[[601.1,393.8],[619.1,393.8],[619.1,411.8],[601.1,411.8]]},{"id":"stairs-west","name":"Stairs","kind":"stairs","anchor":[417.5,618.7],"points":[[408.5,609.7],[426.5,609.7],[426.5,627.7],[408.5,627.7]]},{"id":"stairs-west-main","name":"Stairs","kind":"stairs","anchor":[463.8,902.5],"points":[[454.8,893.5],[472.8,893.5],[472.8,911.5],[454.8,911.5]]},{"id":"stairs-east","name":"Stairs","kind":"stairs","anchor":[1321.4,928.9],"points":[[1312.4,919.9],[1330.4,919.9],[1330.4,937.9],[1312.4,937.9]]},{"id":"stairs-inner","name":"Stairs","kind":"stairs","anchor":[927.4,955.4],"points":[[918.4,946.4],[936.4,946.4],[936.4,964.4],[918.4,964.4]]},{"id":"stairs-centre","name":"Stairs","kind":"stairs","anchor":[794.3,1040.2],"points":[[785.3,1031.2],[803.3,1031.2],[803.3,1049.2],[785.3,1049.2]]},{"id":"stairs-south","name":"Stairs","kind":"stairs","anchor":[1174.8,1118.7],"points":[[1165.8,1109.7],[1183.8,1109.7],[1183.8,1127.7],[1165.8,1127.7]]}]};

// Ground-floor locations confirmed by the owner's annotated plan.
const groundFloorPlaces = [
  ["coffee", "Coffee", "kitchen", [652, 893]],
  ["coffee-seating", "Tables & seating", "room", [766, 807]],
  ["lobby-seating", "Tables & seating", "room", [1143, 818]],
  ["reception", "Reception", "room", [1107, 999]],
  ["build-room", "Build room", "room", [1007, 1131]],
  ["main-entrance", "Main entrance", "room", [1263, 1128]],
  ["secondary-entrance", "Secondary entrance", "room", [649, 1137]],
].map(([id, name, kind, anchor]) => ({
  id, name, kind, anchor,
  points: [[-7,-7],[7,-7],[7,7],[-7,7]].map(([x,y]) => [anchor[0]+x,anchor[1]+y]),
}));
const groundFloorElevators = {
  id: "lift-main", name: "Elevators", kind: "lift", anchor: [763, 940],
  points: [[675.06,986.64],[816.35,856.39],[851.75,894.87],[709.05,1025]],
};

export function applyMapAmenities(data) {
  for (const floor of data.floors) {
    const lower = lowerFloorAmenities[floor.level];
    if (lower) {
      const locations = floor.level === 0
        ? [...lower.map(item => item.id === "lift-main" ? groundFloorElevators : item), ...groundFloorPlaces]
        : lower;
      const ids = new Set(locations.map(item => item.id));
      floor.geometry.wayfinding = [...(floor.geometry.wayfinding || []).filter(item => !ids.has(item.id)), ...locations];
      continue;
    }
    const locations = amenities[floor.level];
    if (!locations) continue;
    const [a, b] = registrations[2], [c, d] = registrations[floor.level];
    const project = p => p.map((value, i) => c[i] + (value - a[i]) * (d[i] - c[i]) / (b[i] - a[i]));
    const elevator = {...elevatorBank, anchor: project(elevatorBank.anchor), points: elevatorBank.points.map(project)};
    const stairs = stairwells.map(stair => ({...stair, anchor: project(stair.anchor), points: stair.points.map(project)}));
    const additions = [...locations, elevator, ...stairs];
    const ids = new Set(additions.map(item => item.id));
    floor.geometry.wayfinding = [...(floor.geometry.wayfinding || []).filter(item => item.kind !== "lift" && !ids.has(item.id)), ...additions];
  }
  applySourcePlanDetails(data);
}
