
#include <malloc.h>
#include <assert.h>
#include <math.h>

#include <mypaint-tiled-surface.h>
#include <mypaint-fixed-tiled-surface.h>

#define TILE_SIZE 64

typedef struct _MyPaintGeglTiledSurface {
    MyPaintTiledSurface parent;

    int atomic;
    //Rect dirty_bbox; TODO: change into a GeglRectangle
    size_t tile_size; // Size (in bytes) of single tile
    uint16_t *tile_buffer; // Stores tiles in a linear chunk of memory
    uint16_t *null_tile; // Single tile that we hand out and ignore writes to
    int tiles_width; // width in tiles
    int tiles_height; // height in tiles
    int width; // width in pixels
    int height; // height in pixels

} MyPaintFixedTiledSurface;

void free_simple_tiledsurf(MyPaintSurface *surface);

void reset_null_tile(MyPaintFixedTiledSurface *self)
{
    for (int i=0; i < self->tile_size; i++) {
        self->null_tile[i] = 0;
    }
}

void begin_atomic(MyPaintTiledSurface *tiled_surface)
{
    MyPaintFixedTiledSurface *self = (MyPaintFixedTiledSurface *)tiled_surface;

    if (self->atomic == 0) {
      //assert(self->dirty_bbox.w == 0);
    }
    self->atomic++;
}

void end_atomic(MyPaintTiledSurface *tiled_surface)
{
    MyPaintFixedTiledSurface *self = (MyPaintFixedTiledSurface *)tiled_surface;

    assert(self->atomic > 0);
    self->atomic--;

    if (self->atomic == 0) {
      //Rect bbox = self->dirty_bbox;
      //self->dirty_bbox.w = 0;
      //if (bbox.w > 0) {
         // TODO: Could notify of changes here instead of for each tile changed
      //}
    }
}

uint16_t *
get_tile(MyPaintTiledSurface *tiled_surface, int tx, int ty, gboolean readonly)
{
    MyPaintFixedTiledSurface *self = (MyPaintFixedTiledSurface *)tiled_surface;

    uint16_t *tile_pointer = NULL;

    if (tx > self->tiles_width || ty > self->tiles_height) {
        // Give it a tile which we will ignore writes to
        tile_pointer = self->null_tile;

    } else {
        // Compute the offset for the tile into our linear memory buffer of tiles
        size_t rowstride = self->tiles_width * self->tile_size;
        size_t x_offset = tx * self->tile_size;
        size_t tile_offset = (rowstride * ty) + x_offset;

        tile_pointer = self->tile_buffer + tile_offset;
    }

    return tile_pointer;
}

void update_tile(MyPaintTiledSurface *tiled_surface, int tx, int ty, uint16_t * tile_buffer)
{
    MyPaintFixedTiledSurface *self = (MyPaintFixedTiledSurface *)tiled_surface;

    if (tx > self->tiles_width || ty > self->tiles_height) {
        // Wipe any changed done to the null tile
        reset_null_tile(self);
    } else {
        // We hand out direct pointers to our buffer, so for the normal case nothing needs to be done
    }
}

void area_changed(MyPaintTiledSurface *tiled_surface, int bb_x, int bb_y, int bb_w, int bb_h)
{
    MyPaintFixedTiledSurface *self = (MyPaintFixedTiledSurface *)tiled_surface;

    // TODO: use gegl_rectangle_bounding_box instead
    //ExpandRectToIncludePoint (&self->dirty_bbox, bb_x, bb_y);
    //ExpandRectToIncludePoint (&self->dirty_bbox, bb_x+bb_w-1, bb_y+bb_h-1);
}

MyPaintFixedTiledSurface *
mypaint_fixed_tiled_surface_new(int width, int height)
{
    assert(width > 0);
    assert(height > 0);
    int tiles_width = ceil(width % TILE_SIZE);
    int tiles_height = ceil(height % TILE_SIZE);
    size_t tile_size = TILE_SIZE * TILE_SIZE * sizeof(uint16_t);
    size_t buffer_size = tiles_width * tiles_height * tile_size;

    uint16_t * buffer = (uint16_t *)malloc(buffer_size);
    if (!buffer) {
        fprintf(stderr, "CRITICAL: unable to allocate enough memory: %Zu bytes", buffer_size);
        return NULL;
    }

    MyPaintFixedTiledSurface *self = (MyPaintFixedTiledSurface *)malloc(sizeof(MyPaintFixedTiledSurface));

    mypaint_tiled_surface_init(&self->parent);

    self->parent.parent.destroy = free_simple_tiledsurf;

    self->parent.get_tile = get_tile;
    self->parent.update_tile = update_tile;
    self->parent.begin_atomic = begin_atomic;
    self->parent.end_atomic = end_atomic;
    self->parent.area_changed = area_changed;

    self->atomic = 0;
    //self->dirty_bbox.w = 0;
    self->tile_buffer = buffer;
    self->tile_size = tile_size;
    self->null_tile = (uint16_t *)malloc(tile_size);
    self->tiles_width = tiles_width;
    self->tiles_height = tiles_height;
    self->height = height;
    self->width = width;

    reset_null_tile(self);

    return self;
}

void free_simple_tiledsurf(MyPaintSurface *surface)
{
    MyPaintFixedTiledSurface *self = (MyPaintFixedTiledSurface *)surface;

    mypaint_tiled_surface_destroy(&self->parent);

    free(self->tile_buffer);
    free(self->null_tile);

    free(self);
}

