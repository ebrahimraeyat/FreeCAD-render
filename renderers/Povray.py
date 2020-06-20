# ***************************************************************************
# *                                                                         *
# *   Copyright (c) 2017 Yorik van Havre <yorik@uncreated.net>              *
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

"""POV-Ray renderer for FreeCAD"""

# Suggested documentation link:
# https://www.povray.org/documentation/3.7.0/r3_0.html#r3_1

# NOTE:
# Please note that POV-Ray coordinate system appears to be different from
# FreeCAD's one (z and y permuted)
# See here: https://www.povray.org/documentation/3.7.0/t2_2.html#t2_2_1_1

import os
import re
from textwrap import dedent

import FreeCAD as App


# ===========================================================================
#                             Write functions
# ===========================================================================


def write_object(name, mesh, color, alpha):
    """Compute a string in the format of POV-Ray, that represents a FreeCAD
    object
    """

    # This is where you write your object/view in the format of your
    # renderer. "obj" is the real 3D object handled by this project, not
    # the project itself. This is your only opportunity
    # to write all the data needed by your object (geometry, materials, etc)
    # so make sure you include everything that is needed

    snippet = """
    // Generated by FreeCAD (http://www.freecadweb.org/)
    // Declares object '{name}'
    #declare {name} = mesh2 {{
        vertex_vectors {{
            {len_vertices},
            {vertices}
        }}
        normal_vectors {{
            {len_normals},
            {normals}
        }}
        face_indices {{
            {len_indices},
            {indices}
        }}
    }}  // {name}

    // Instance to render {name}
    object {{ {name}
        texture {{
            pigment {{
                color rgb {color}
            }}
            finish {{StdFinish}}
        }}
    }}  // {name}\n"""

    colo = "<{},{},{}>".format(*color)
    vrts = ["<{0.x},{0.z},{0.y}>".format(v) for v in mesh.Topology[0]]
    nrms = ["<{0.x},{0.z},{0.y}>".format(n) for n in mesh.getPointNormals()]
    inds = ["<{},{},{}>".format(*i) for i in mesh.Topology[1]]

    return dedent(snippet).format(name=name,
                                  len_vertices=len(vrts),
                                  vertices="\n        ".join(vrts),
                                  len_normals=len(nrms),
                                  normals="\n        ".join(nrms),
                                  len_indices=len(inds),
                                  indices="\n        ".join(inds),
                                  color=colo)


def write_camera(name, pos, updir, target):
    """Compute a string in the format of POV-Ray, that represents a camera"""

    # This is where you create a piece of text in the format of
    # your renderer, that represents the camera.

    snippet = """
    // Generated by FreeCAD (http://www.freecadweb.org/)
    // Declares camera '{n}'
    #declare cam_location = <{p.x},{p.z},{p.y}>;
    #declare cam_look_at  = <{t.x},{t.z},{t.y}>;
    #declare cam_sky      = <{u.x},{u.z},{u.y}>;
    #declare cam_angle    = 45;
    camera {{
        location  cam_location
        look_at   cam_look_at
        sky       cam_sky
        angle     cam_angle
        right     x*800/600
    }}\n"""

    return dedent(snippet).format(n=name, p=pos.Base, t=target, u=updir)


def write_pointlight(name, pos, color, power):
    """Compute a string in the format of POV-Ray, that represents a
    PointLight object
    """
    # This is where you write the renderer-specific code
    # to export the point light in the renderer format

    # Note: power is of no use for POV-Ray, as light intensity is determined
    # by RGB (see POV-Ray documentation)
    snippet = """
    // Generated by FreeCAD (http://www.freecadweb.org/)
    // Declares point light {0}
    light_source {{
        <{1.x},{1.z},{1.y}>
        color rgb<{2[0]},{2[1]},{2[2]}>
    }}\n"""

    return dedent(snippet).format(name, pos, color)


def write_arealight(name, pos, size_u, size_v, color, power):
    """Compute a string in the format of Povray, that represents an
    Area Light object
    """
    # Dimensions of the point sources array
    # (area light is treated as points source array, see POV-Ray documentation)
    size_1 = 20
    size_2 = 20

    # Prepare area light axes
    rot = pos.Rotation
    axis1 = rot.multVec(App.Vector(size_u, 0.0, 0.0))
    axis2 = rot.multVec(App.Vector(0.0, size_v, 0.0))

    snippet = """
    // Generated by FreeCAD (http://www.freecadweb.org/)
    // Declares area light {n}
    light_source {{
        <{o.x},{o.z},{o.y}>
        color rgb <{c[0]},{c[1]},{c[2]}>
        area_light <{u.x},{u.z},{u.y}>, <{v.x},{v.z},{v.y}>, {a}, {b}
        adaptive 1
        jitter
    }}\n"""

    return dedent(snippet).format(n=name,
                                  o=pos.Base,
                                  c=color,
                                  u=axis1,
                                  v=axis2,
                                  a=size_1,
                                  b=size_2)


def write_sunskylight(name, direction, distance, turbidity):
    """Compute a string in the format of Povray, that represents an
    Sunsky object

    Since POV-Ray does not provide a built-in Hosek-Wilkie feature, sunsky is
    modeled by a white parallel light, with a simple gradient skysphere.
    Please note it is a very approximate and limited model (works better for
    sun high in the sky...)
    """
    location = direction.normalize()
    location.Length = distance

    snippet = """
    // Generated by FreeCAD (http://www.freecadweb.org/)
    // Declares sunsky light {n}
    // sky ------------------------------------
    sky_sphere{{
        pigment{{ gradient y
           color_map{{
               [0.0 color rgb<1,1,1> ]
               [0.8 color rgb<0.18,0.28,0.75>]
               [1.0 color rgb<0.75,0.75,0.75>]}}
               //[1.0 color rgb<0.15,0.28,0.75>]}}
               scale 2
               translate -1
        }} // end pigment
    }} // end sky_sphere
    // sun -----------------------------------
    global_settings {{ ambient_light rgb<1, 1, 1> }}
    light_source {{
        <{o.x},{o.z},{o.y}>
        color rgb <1,1,1>
        parallel
        point_at <0,0,0>
        adaptive 1
    }}\n"""

    return dedent(snippet).format(n=name,
                                  o=location)


def write_imagelight(name, image):
    """Compute a string in the format of Povray, that represents an
    image-based light object"""
    snippet = """
    // Generated by FreeCAD (http://www.freecadweb.org/)
    // Declares image-based light {n}
    // hdr environment -----------------------
    sky_sphere{{
        matrix < -1, 0, 0,
                  0, 1, 0,
                  0, 0, 1,
                  0, 0, 0 >
        pigment{{
            image_map{{ hdr "{f}"
                       gamma 1
                       map_type 1 interpolate 2}}
        }} // end pigment
    }} // end sphere with hdr image\n"""

    return dedent(snippet).format(n=name,
                                  f=image)


# ===========================================================================
#                              Render function
# ===========================================================================


def render(project, prefix, external, output, width, height):
    """Run POV-Ray

    Params:
    - project:  the project to render
    - prefix:   a prefix string for call (will be inserted before path to Lux)
    - external: a boolean indicating whether to call UI (true) or console
                (false) version of Lux
    - width:    rendered image width, in pixels
    - height:   rendered image height, in pixels

    Return: path to output image file
    """

    # Here you trigger a render by firing the renderer
    # executable and passing it the needed arguments, and
    # the file it needs to render

    params = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Render")

    prefix = params.GetString("Prefix", "")
    if prefix:
        prefix += " "

    rpath = params.GetString("PovRayPath", "")
    if not rpath:
        App.Console.PrintError("Unable to locate renderer executable. "
                               "Please set the correct path in "
                               "Edit -> Preferences -> Render\n")
        return ""

    args = params.GetString("PovRayParameters", "")
    if args:
        args += " "
    if "+W" in args:
        args = re.sub(r"\+W[0-9]+", "+W{}".format(width), args)
    else:
        args = args + "+W{} ".format(width)
    if "+H" in args:
        args = re.sub(r"\+H[0-9]+", "+H{}".format(height), args)
    else:
        args = args + "+H{} ".format(height)
    if output:
        args = args + "+O{} ".format(output)

    cmd = prefix + rpath + " " + args + project.PageResult
    App.Console.PrintMessage("Renderer command: %s\n" % cmd)
    os.system(cmd)

    return output if output else os.path.splitext(project.PageResult)[0]+".png"
