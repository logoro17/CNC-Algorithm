(=====================================================)
( TEST SAMPLE FOR ROUTE OPTIMIZATION ALGORITHMS       )
( Contains 4 isolated contours placed in 4 quadrants  )
( Intentionally unoptimized rapid moves               )
( Target: X: 0-100 mm, Y: 0-100 mm                    )
(=====================================================)

G21 (Units in mm)
G90 (Absolute Distance Mode)
G00 X0 Y0 Z5.000 (Go to home position)

( --- CONTOUR 1: Upper-Right Square [X: 60-90, Y: 60-90] --- )
G00 X60.000 Y60.000 (Rapid to start)
G01 Z-1.000 F300.0 (Plunge)
G01 X90.000 Y60.000 F800.0
G01 X90.000 Y90.000
G01 X60.000 Y90.000
G01 X60.000 Y60.000
G00 Z5.000 (Retract)

( --- CONTOUR 2: Lower-Left Triangle [X: 10-40, Y: 10-40] --- )
( Notice the unoptimized jump across the bed )
G00 X10.000 Y10.000
G01 Z-1.000 F300.0
G01 X40.000 Y10.000 F800.0
G01 X25.000 Y40.000
G01 X10.000 Y10.000
G00 Z5.000

( --- CONTOUR 3: Upper-Left Circle approximation [X: 10-40, Y: 60-90] --- )
( Jumping diagonally back up )
G00 X25.000 Y60.000
G01 Z-1.000 F300.0
G01 X35.607 Y64.393 F800.0
G01 X40.000 Y75.000
G01 X35.607 Y85.607
G01 X25.000 Y90.000
G01 X14.393 Y85.607
G01 X10.000 Y75.000
G01 X14.393 Y64.393
G01 X25.000 Y60.000
G00 Z5.000

( --- CONTOUR 4: Lower-Right Diamond [X: 60-90, Y: 10-40] --- )
( Jumping diagonally back down )
G00 X75.000 Y10.000
G01 Z-1.000 F300.0
G01 X90.000 Y25.000 F800.0
G01 X75.000 Y40.000
G01 X60.000 Y25.000
G01 X75.000 Y10.000
G00 Z5.000

( --- END OF PROGRAM --- )
G00 X0 Y0 Z10.000 (Return Home)
M30
