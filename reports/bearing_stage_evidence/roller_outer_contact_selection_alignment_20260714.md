# Roller outer contact selection alignment

- Source root: `runtime_smoke/bearing_family_p12_boundaryload_outer_x31_box_intersection`
- Reference abs radial delta mm: `2.246617394014775`

| Roller | Source entities | Destination entities | Source proj mm | Destination proj mm | Abs delta mm | Ratio vs ref |
|---|---|---|---:|---:|---:|---:|
| roller_1 | [188, 187] | [9, 8] | 29.5463 | 19.7352 | 9.81111 | 4.36706 |
| roller_2 | [181, 182] | [9] | 29.2054 | 26.9588 | 2.24662 | 1 |
| roller_12 | [175, 176] | [8] | 29.2054 | 26.9588 | 2.24662 | 0.999999 |

## Conclusion

roller_1 outer source/destination selections are geometrically mismatched relative to nonzero roller_2/12 references; repair should create matched local patches before solve.
