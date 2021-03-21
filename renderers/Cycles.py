# ***************************************************************************
# *                                                                         *
# *   Copyright (c) 2019 Yorik van Havre <yorik@uncreated.net>              *
# *                                                                         *
# *   This program is free software; you can redistribute it and/or modify  *
# *   it under the terms of the GNU Lesser General Public License (LGPL)    *
# *   as published by the Free Software Foundation; either version 2 of     *
# *   the License, or (at your option) any later version.                   *
# *   for detail see the LICENCE text file.                                 *
# *                                                                         *
# *   This program is distributed in the hope that it will be useful,       *
# *   but WITHOUT ANY WARRANTY; without even the implied warranty of        *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         *
# *   GNU Library General Public License for more details.                  *
# *                                                                         *
# *   You should have received a copy of the GNU Library General Public     *
# *   License along with this program; if not, write to the Free Software   *
# *   Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  *
# *   USA                                                                   *
# *                                                                         *
# ***************************************************************************

"""Cycles renderer plugin for FreeCAD Render workbench."""

# Suggested documentation links:
# NOTE Standalone Cycles is experimental, so no documentation is available.
# Instead, documentation must be searched directly in code (via reverse
# engineering), and in the examples provided with it.
# Here are some links:
# https://wiki.blender.org/wiki/Source/Render/Cycles/Standalone
# https://developer.blender.org/diffusion/C/browse/master/src/
# https://developer.blender.org/diffusion/C/browse/master/src/render/nodes.cpp
# https://developer.blender.org/diffusion/C/browse/master/src/app/cycles_xml.cpp
# https://developer.blender.org/diffusion/C/browse/master/examples/
#
# A few hints (my understanding of cycles_standalone):
#
# The 'int main()' is in 'src/app/cycles_standalone.cpp' (but you may not be
# most interested in it)
#
# The xml input file is processed by 'src/app/cycles_xml.cpp' functions.
# The entry point is 'xml_read_file', which cascades to 'xml_read_scene' via
# 'xml_read_include' function.
#
# 'xml_read_scene' is a key function to study: it recognizes and dispatches all
# the possible nodes to 'xml_read_*' node-specialized parsing functions.
# A few more 'xml_read_*' (including 'xml_read_node' are defined in
# /src/graph/node_xml.cpp


import os
import pathlib
from math import degrees, asin, sqrt, radians, atan2
from textwrap import indent

import FreeCAD as App

from renderers.utils.sunlight import sunlight


# ===========================================================================
#                             Write functions
# ===========================================================================


def write_object(name, mesh, material):
    """Compute a string in renderer SDL to represent a FreeCAD object."""
    snippet_mat = _write_material(name, material)

    snippet_obj = """
    <state shader="{n}">
        <mesh P="{p}"
              nverts="{i}"
              verts="{v}"/>
    </state>\n"""

    snippet = snippet_mat + snippet_obj

    points = ["{0.x} {0.y} {0.z}".format(p) for p in mesh.Topology[0]]
    verts = ["{} {} {}".format(*v) for v in mesh.Topology[1]]
    nverts = ["3"] * len(verts)

    return snippet.format(n=name,
                          p="  ".join(points),
                          i="  ".join(nverts),
                          v="  ".join(verts))


def write_camera(name, pos, updir, target, fov):
    """Compute a string in renderer SDL to represent a camera."""
    # This is where you create a piece of text in the format of
    # your renderer, that represents the camera.

    # Cam rotation is angle(deg) axisx axisy axisz
    # Scale needs to have z inverted to behave like a decent camera.
    # No idea what they have been doing at blender :)
    snippet = """
    <!-- Generated by FreeCAD - Camera '{n}' -->
    <transform rotate="{a} {r.x} {r.y} {r.z}"
               translate="{p.x} {p.y} {p.z}"
               scale="1 1 -1">
        <camera type="perspective"
                fov="{f}"/>
    </transform>"""

    return snippet.format(n=name,
                          a=degrees(pos.Rotation.Angle),
                          r=pos.Rotation.Axis,
                          p=pos.Base,
                          f=radians(fov))


def write_pointlight(name, pos, color, power):
    """Compute a string in renderer SDL to represent a point light."""
    # This is where you write the renderer-specific code
    # to export a point light in the renderer format

    snippet = """
    <!-- Generated by FreeCAD - Pointlight '{n}' -->
    <shader name="{n}_shader">
        <emission name="{n}_emit"
                  color="{c[0]} {c[1]} {c[2]}"
                  strength="{s}"/>
        <connect from="{n}_emit emission"
                 to="output surface"/>
    </shader>
    <state shader="{n}_shader">
        <light type="point"
               co="{p.x} {p.y} {p.z}"
               strength="1 1 1"/>
    </state>\n"""

    return snippet.format(n=name,
                          c=color,
                          p=pos,
                          s=power*100)


def write_arealight(name, pos, size_u, size_v, color, power, transparent):
    """Compute a string in renderer SDL to represent an area light."""

    # Transparent area light
    rot = pos.Rotation
    axis1 = rot.multVec(App.Vector(1.0, 0.0, 0.0))
    axis2 = rot.multVec(App.Vector(0.0, 1.0, 0.0))
    direction = axis1.cross(axis2)
    snippet1 = """
    <!-- Generated by FreeCAD - Area light '{n}' (transparent) -->
    <shader name="{n}_shader">
        <emission name="{n}_emit"
                  color="{c[0]} {c[1]} {c[2]}"
                  strength="{s}"/>
        <connect from="{n}_emit emission"
                 to="output surface"/>
    </shader>
    <state shader="{n}_shader">
        <light type="area"
               co="{p.x} {p.y} {p.z}"
               strength="1 1 1"
               axisu="{u.x} {u.y} {u.z}"
               axisv="{v.x} {v.y} {v.z}"
               sizeu="{a}"
               sizev="{b}"
               size="1"
               dir="{d.x} {d.y} {d.z}"
               use_mis = "true"
        />
    </state>\n"""

    # Opaque area light (--> mesh light)
    points = [(-size_u / 2, -size_v / 2, 0),
              (+size_u / 2, -size_v / 2, 0),
              (+size_u / 2, +size_v / 2, 0),
              (-size_u / 2, +size_v / 2, 0)]
    points = [pos.multVec(App.Vector(*p)) for p in points]
    points = ["{0.x} {0.y} {0.z}".format(p) for p in points]
    points = "  ".join(points)

    snippet2 = """
    <!-- Generated by FreeCAD - Area light '{n}' (opaque) -->
    <shader name="{n}_shader" use_mis="true">
        <emission name="{n}_emit"
                  color="{c[0]} {c[1]} {c[2]}"
                  strength="{s}"/>
        <connect from="{n}_emit emission"
                 to="output surface"/>
    </shader>
    <state shader="{n}_shader">
        <mesh P="{P}"
              nverts="4"
              verts="0 1 2 3"
              use_mis="true"
              />
    </state>\n"""

    snippet = snippet1 if transparent else snippet2
    strength = power if transparent else power / (size_u * size_v)

    return snippet.format(n=name,
                          c=color,
                          p=pos.Base,
                          s=strength * 100,
                          u=axis1,
                          v=axis2,
                          a=size_u,
                          b=size_v,
                          d=direction,
                          P=points)


def write_sunskylight(name, direction, distance, turbidity, albedo):
    """Compute a string in renderer SDL to represent a sunsky light."""
    # We use the new improved nishita model (2020)

    assert direction.Length
    _dir = App.Vector(direction)
    _dir.normalize()
    theta = asin(_dir.z / sqrt(_dir.x**2 + _dir.y**2 + _dir.z**2))
    phi = atan2(_dir.x, _dir.y)
    sun = sunlight(theta, turbidity)


    snippet = """
    <!-- Generated by FreeCAD - Sun_sky light '{n}' -->
    <background name="{n}_bg">
          <background name="{n}_bg" strength="0.3"/>
          <sky_texture name="{n}_tex"
                       sky_type="nishita_improved"
                       turbidity="{t}"
                       ground_albedo="{g}"
                       sun_disc="true"
                       sun_elevation="{e}"
                       sun_rotation="{r}"
                       />
          <connect from="{n}_tex color" to="{n}_bg color" />
          <connect from="{n}_bg background" to="output surface" />
    </background>\n"""

    return snippet.format(n=name,
                          t=turbidity,
                          g=albedo,
                          e=theta,
                          r=phi
                         )


def write_imagelight(name, image):
    """Compute a string in renderer SDL to represent an image-based light."""
    # Caveat: Cycles requires the image file to be in the same directory
    # as the input file
    filename = pathlib.Path(image).name
    snippet = """
    <!-- Generated by FreeCAD - Image-based light '{n}' -->
    <background>
          <background name="{n}_bg" />
          <environment_texture name= "{n}_tex"
                               filename = "{f}" />
          <connect from="{n}_tex color" to="{n}_bg color" />
          <connect from="{n}_bg background" to="output surface" />
    </background>\n"""
    return snippet.format(n=name,
                          f=filename,)


# ===========================================================================
#                              Material implementation
# ===========================================================================


def _write_material(name, material):
    """Compute a string in the renderer SDL, to represent a material.

    This function should never fail: if the material is not recognized,
    a fallback material is provided.
    """
    try:
        snippet_mat = MATERIALS[material.shadertype](name, material)
    except KeyError:
        msg = ("'{}' - Material '{}' unknown by renderer, using fallback "
               "material\n")
        App.Console.PrintWarning(msg.format(name, material.shadertype))
        snippet_mat = _write_material_fallback(name, material.default_color)
    return snippet_mat


def _write_material_passthrough(name, material):
    """Compute a string in the renderer SDL for a passthrough material."""
    assert material.passthrough.renderer == "Cycles"
    snippet = indent(material.passthrough.string, "    ")
    return snippet.format(n=name, c=material.default_color)


def _write_material_glass(name, material):
    """Compute a string in the renderer SDL for a glass material."""
    snippet = """
    <!-- Generated by FreeCAD - Object '{n}' -->
    <shader name="{n}">
        <glass_bsdf name="{n}_bsdf" IOR="{i}" color="{c.r}, {c.g}, {c.b}"/>
        <connect from="{n}_bsdf bsdf" to="output surface"/>
    </shader>"""

    return snippet.format(n=name,
                          c=material.glass.color,
                          i=material.glass.ior)


def _write_material_disney(name, material):
    """Compute a string in the renderer SDL for a Disney material."""
    snippet = """
    <!-- Generated by FreeCAD - Object '{0}' -->
    <shader name="{0}">
        <principled_bsdf name="{0}_bsdf"
                         base_color = "{1.r} {1.g} {1.b}"
                         subsurface = "{2}"
                         metallic = "{3}"
                         specular = "{4}"
                         specular_tint = "{5}"
                         roughness = "{6}"
                         anisotropic = "{7}"
                         sheen = "{8}"
                         sheen_tint = "{9}"
                         clearcoat = "{10}"
                         clearcoat_roughness = "{11}" />
        <connect from="{0}_bsdf bsdf" to="output surface"/>
    </shader>"""
    return snippet.format(name,
                          material.disney.basecolor,
                          material.disney.subsurface,
                          material.disney.metallic,
                          material.disney.specular,
                          material.disney.speculartint,
                          material.disney.roughness,
                          material.disney.anisotropic,
                          material.disney.sheen,
                          material.disney.sheentint,
                          material.disney.clearcoat,
                          1 - float(material.disney.clearcoatgloss))


def _write_material_diffuse(name, material):
    """Compute a string in the renderer SDL for a Diffuse material."""
    snippet = """
    <!-- Generated by FreeCAD - Object '{n}' -->
    <shader name="{n}">
        <diffuse_bsdf name="{n}_bsdf" color="{c.r}, {c.g}, {c.b}"/>
        <connect from="{n}_bsdf bsdf" to="output surface"/>
    </shader>"""
    return snippet.format(n=name,
                          c=material.diffuse.color)


def _write_material_mixed(name, material):
    """Compute a string in the renderer SDL for a Mixed material."""
    snippet = """
    <!-- Generated by FreeCAD - Object '{n}' -->
    <shader name="{n}">
        <glass_bsdf name="{n}_glass_bsdf"
                    IOR="{i}" color="{c.r}, {c.g}, {c.b}"/>
        <diffuse_bsdf name="{n}_diffuse_bsdf" color="{k.r}, {k.g}, {k.b}"/>
        <mix_closure name="{n}_closure" fac="{r}" />
        <connect from="{n}_diffuse_bsdf bsdf" to="{n}_closure closure1"/>
        <connect from="{n}_glass_bsdf bsdf" to="{n}_closure closure2"/>
        <connect from="{n}_closure closure" to="output surface"/>
    </shader>"""
    return snippet.format(n=name,
                          c=material.mixed.glass.color,
                          i=material.mixed.glass.ior,
                          k=material.mixed.diffuse.color,
                          r=material.mixed.transparency)


def _write_material_fallback(name, material):
    """Compute a string in the renderer SDL for a fallback material.

    Fallback material is a simple Diffuse material.
    """
    try:
        red = float(material.default_color.r)
        grn = float(material.default_color.g)
        blu = float(material.default_color.b)
        assert (0 <= red <= 1) and (0 <= grn <= 1) and (0 <= blu <= 1)
    except (AttributeError, ValueError, TypeError, AssertionError):
        red, grn, blu = 1, 1, 1
    snippet = """
    <!-- Generated by FreeCAD - Object '{n}' - FALLBACK -->
    <shader name="{n}">
        <diffuse_bsdf name="{n}_bsdf" color="{r}, {g}, {b}"/>
        <connect from="{n}_bsdf bsdf" to="output surface"/>
    </shader>"""
    return snippet.format(n=name,
                          r=red,
                          g=grn,
                          b=blu)


MATERIALS = {
        "Passthrough": _write_material_passthrough,
        "Glass": _write_material_glass,
        "Disney": _write_material_disney,
        "Diffuse": _write_material_diffuse,
        "Mixed": _write_material_mixed}


# ===========================================================================
#                              Render function
# ===========================================================================


def render(project, prefix, external, output, width, height):
    """Run renderer.

    Args:
        project -- The project to render
        prefix -- A prefix string for call (will be inserted before path to
            renderer)
        external -- A boolean indicating whether to call UI (true) or console
            (false) version of renderder
        width -- Rendered image width, in pixels
        height -- Rendered image height, in pixels

    Returns:
        A path to output image file
    """
    # Here you trigger a render by firing the renderer
    # executable and passing it the needed arguments, and
    # the file it needs to render
    params = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Render")
    prefix = params.GetString("Prefix", "")
    if prefix:
        prefix += " "
    rpath = params.GetString("CyclesPath", "")
    args = params.GetString("CyclesParameters", "")
    args += " --output " + output
    if not external:
        args += " --background"
    if not rpath:
        App.Console.PrintError("Unable to locate renderer executable. "
                               "Please set the correct path in "
                               "Edit -> Preferences -> Render\n")
        return ""
    args += " --width " + str(width)
    args += " --height " + str(height)
    cmd = prefix + rpath + " " + args + " " + project.PageResult
    App.Console.PrintMessage(cmd+'\n')
    os.system(cmd)

    return output
