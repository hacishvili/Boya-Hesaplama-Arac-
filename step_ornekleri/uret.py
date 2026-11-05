# -*- coding: utf-8 -*-
"""step_ornekleri/*.step örneklerini üretir (Open CASCADE ile; yalnız örnekleri yenilemek için, testler gerektirmez).
  pip install cadquery-ocp ; python step_ornekleri/uret.py <ocp klasörünün üstü>"""
import sys, json
sys.path.insert(0, sys.argv[1] + "/ocp")
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder, BRepPrimAPI_MakeCone, BRepPrimAPI_MakeSphere, BRepPrimAPI_MakeTorus, BRepPrimAPI_MakeRevol, BRepPrimAPI_MakePrism
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet
from OCP.gp import gp_Ax2, gp_Pnt, gp_Dir, gp_Vec, gp_Trsf, gp_Ax1
from OCP.STEPControl import STEPControl_Writer, STEPControl_AsIs
from OCP.Interface import Interface_Static
from OCP.GProp import GProp_GProps
from OCP.BRepGProp import BRepGProp
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_EDGE
from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform, BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire, BRepBuilderAPI_MakeFace
from OCP.TopoDS import TopoDS_Compound, TopoDS
from OCP.BRep import BRep_Builder
from OCP.Geom import Geom_BSplineCurve

from OCP.GeomAPI import GeomAPI_PointsToBSpline
import os
out = os.path.dirname(os.path.abspath(__file__)) + "/"
def alan(s):
    g = GProp_GProps(); BRepGProp.SurfaceProperties_s(s, g); return g.Mass()
def yaz(ad, s, birim="MM"):
    Interface_Static.SetCVal_s("write.step.unit", birim)
    w = STEPControl_Writer(); w.Transfer(s, STEPControl_AsIs); w.Write(out + ad + ".step")
ref = {}
# 1 plaka: delik + havşa (koni) + kanal
plaka = BRepPrimAPI_MakeBox(100, 60, 5).Shape()
d1 = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(20, 20, -1), gp_Dir(0, 0, 1)), 3, 10).Shape()
hv = BRepPrimAPI_MakeCone(gp_Ax2(gp_Pnt(80, 20, 2), gp_Dir(0, 0, 1)), 3, 6, 3).Shape()  # 90° havşa: r 3→6, h 3
d2 = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(80, 20, -1), gp_Dir(0, 0, 1)), 3, 10).Shape()
s = plaka
for t in (d1, hv, d2):
    s = BRepAlgoAPI_Cut(s, t).Shape()
ref["plaka"] = alan(s); yaz("plaka", s)
yaz("plaka_inc", s, "INCH"); ref["plaka_inc"] = alan(s)
# 2 kavisli: kutu + fileto (silindir/torus/spline olabilir) + küre çıkıntı
k = BRepPrimAPI_MakeBox(40, 30, 20).Shape()
f = BRepFilletAPI_MakeFillet(k)
e = TopExp_Explorer(k, TopAbs_EDGE)
while e.More():
    f.Add(4.0, TopoDS.Edge(e.Current())); e.Next()
s2 = f.Shape()
ref["fileto"] = alan(s2); yaz("fileto", s2)
# 3 dönel: spline profil döndürülür (SURFACE_OF_REVOLUTION) + çekim (LINEAR_EXTRUSION)
pts = []
for i, (x, z) in enumerate([(10, 0), (14, 10), (9, 20), (12, 30)], 1):
    pts.append(gp_Pnt(x, 0, z))
from OCP.OCP.collections import Array1_gp_Pnt
arr = Array1_gp_Pnt(1, 4)
for i, q in enumerate(pts, 1):
    arr.SetValue(i, q)
bs = GeomAPI_PointsToBSpline(arr).Curve()
e1 = BRepBuilderAPI_MakeEdge(bs).Edge()
rev = BRepPrimAPI_MakeRevol(e1, gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1))).Shape()
ref["donel"] = alan(rev); yaz("donel", rev)
pr = BRepPrimAPI_MakePrism(e1, gp_Vec(0, 25, 0)).Shape()
ref["cekim"] = alan(pr); yaz("cekim", pr)
# 4 montaj benzeri: sac + 2 boru (ayrı katılar, bileşik)
b = BRep_Builder(); c = TopoDS_Compound(); b.MakeCompound(c)
sac = BRepPrimAPI_MakeBox(100, 60, 5).Shape()
b.Add(c, sac)
for x in (30, 70):
    b.Add(c, BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(x, 30, 5), gp_Dir(0, 0, 1)), 10, 80).Shape())
ref["montaj"] = alan(c); ref["montaj_boru"] = alan(BRepPrimAPI_MakeCylinder(10, 80).Shape()); yaz("montaj", c)
# 5 küre + torus + koni
b2 = BRep_Builder(); c2 = TopoDS_Compound(); b2.MakeCompound(c2)
for s_ in (BRepPrimAPI_MakeSphere(gp_Pnt(0, 0, 0), 10).Shape(), BRepPrimAPI_MakeTorus(gp_Ax2(gp_Pnt(50, 0, 0), gp_Dir(0, 1, 0)), 20, 5).Shape(),
           BRepPrimAPI_MakeCone(gp_Ax2(gp_Pnt(-50, 0, 0), gp_Dir(1, 1, 0)), 10, 0, 20).Shape()):
    b2.Add(c2, s_)
ref["donel_cisimler"] = [alan(BRepPrimAPI_MakeSphere(10).Shape()), alan(BRepPrimAPI_MakeTorus(20, 5).Shape()), alan(BRepPrimAPI_MakeCone(10, 0, 20).Shape())]
yaz("cisimler", c2)
print(ref)


# ---- montaj (masa.step)
import sys, json, math
sys.path.insert(0, sys.argv[1] + "/ocp")
from OCP.TDocStd import TDocStd_Document
from OCP.TCollection import TCollection_ExtendedString
from OCP.XCAFDoc import XCAFDoc_DocumentTool
from OCP.STEPCAFControl import STEPCAFControl_Writer
from OCP.STEPControl import STEPControl_AsIs
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
from OCP.gp import gp_Trsf, gp_Vec, gp_Ax1, gp_Pnt, gp_Dir, gp_Ax2
from OCP.TopLoc import TopLoc_Location
from OCP.TDataStd import TDataStd_Name
doc = TDocStd_Document(TCollection_ExtendedString("XmlOcaf"))
st = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
ayak = BRepPrimAPI_MakeBox(20, 20, 200).Shape()
ayak = BRepAlgoAPI_Cut(ayak, BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(10, -1, 180), gp_Dir(0, 1, 0)), 4, 30).Shape()).Shape()
tabla = BRepPrimAPI_MakeBox(400, 300, 10).Shape()
la = st.AddShape(ayak, False); TDataStd_Name.Set_s(la, TCollection_ExtendedString("AYAK"))
lt = st.AddShape(tabla, False); TDataStd_Name.Set_s(lt, TCollection_ExtendedString("TABLA"))
asm = st.NewShape(); TDataStd_Name.Set_s(asm, TCollection_ExtendedString("MASA"))
for i, (x, y) in enumerate([(0, 0), (380, 0), (0, 280), (380, 280)]):
    t = gp_Trsf(); t.SetRotation(gp_Ax1(gp_Pnt(10, 10, 0), gp_Dir(0, 0, 1)), math.radians(90 * i))
    t2 = gp_Trsf(); t2.SetTranslation(gp_Vec(x, y, -200)); t2.Multiply(t)
    st.AddComponent(asm, la, TopLoc_Location(t2))
st.AddComponent(asm, lt, TopLoc_Location())
st.UpdateAssemblies()
w = STEPCAFControl_Writer(); w.Transfer(doc, STEPControl_AsIs); w.Write(out + "masa.step")
from OCP.GProp import GProp_GProps
from OCP.BRepGProp import BRepGProp
g = GProp_GProps(); BRepGProp.SurfaceProperties_s(ayak, g)
print("ayak", g.Mass())
