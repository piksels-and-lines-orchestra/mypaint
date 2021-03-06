/* brushlib - The MyPaint Brush Library
 * Copyright (C) 2008 Martin Renold <martinxyz@gmx.ch>
 *
 * Permission to use, copy, modify, and/or distribute this software for any
 * purpose with or without fee is hereby granted, provided that the above
 * copyright notice and this permission notice appear in all copies.
 *
 * THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
 * WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
 * MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
 * ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
 * WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
 * ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
 * OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.
 */

#ifndef SURFACE_HPP
#define SURFACE_HPP

typedef struct _MyPaintSurface MyPaintSurface;

// surface interface required by brush.hpp
class Surface {
public:

  virtual ~Surface() {}

  virtual bool draw_dab (float x, float y, 
                         float radius, 
                         float color_r, float color_g, float color_b,
                         float opaque, float hardness = 0.5,
                         float alpha_eraser = 1.0,
                         float aspect_ratio = 1.0, float angle = 0.0,
                         float lock_alpha = 0.0,
                         float colorize = 0.0,
                         int recursing = 0 // used for symmetry, internal use only
                         ) = 0;

  virtual void get_color (float x, float y, 
                          float radius, 
                          float * color_r, float * color_g, float * color_b, float * color_a
                          ) = 0;

  virtual MyPaintSurface *get_surface_interface() = 0;
};

#endif //SURFACE_HPP
