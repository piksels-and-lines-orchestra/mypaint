// gtk stock code - left gtk prefix to use the pygtk wrapper-generator easier
#include "gtkmydrawwidget.h"

static void gtk_my_draw_widget_class_init    (GtkMyDrawWidgetClass *klass);
static void gtk_my_draw_widget_finalize (GObject *object);
static void gtk_my_draw_widget_realize (GtkWidget *widget);
static gint gtk_my_draw_widget_button_updown (GtkWidget *widget, GdkEventButton *event);
static gint gtk_my_draw_widget_motion_notify (GtkWidget *widget, GdkEventMotion *event);
static gint gtk_my_draw_widget_proximity_inout (GtkWidget *widget, GdkEventProximity *event);
static gint gtk_my_draw_widget_expose (GtkWidget *widget, GdkEventExpose *event);

static gpointer parent_class;

GType
gtk_my_draw_widget_get_type (void)
{
  static GType my_draw_widget_type = 0;

  if (!my_draw_widget_type)
    {
      static const GTypeInfo my_draw_widget_info =
      {
	sizeof (GtkMyDrawWidgetClass),
	NULL,		/* base_init */
	NULL,		/* base_finalize */
	(GClassInitFunc) gtk_my_draw_widget_class_init,
	NULL,		/* class_finalize */
	NULL,		/* class_data */
	sizeof (GtkMyDrawWidget),
	0,		/* n_preallocs */
	NULL, /* instance init */
      };

      my_draw_widget_type =
	g_type_register_static (GTK_TYPE_DRAWING_AREA, "GtkMyDrawWidget",
				&my_draw_widget_info, 0);
    }

  return my_draw_widget_type;
}

static void
gtk_my_draw_widget_class_init (GtkMyDrawWidgetClass *class)
{
  GtkWidgetClass *widget_class = GTK_WIDGET_CLASS (class);
  GObjectClass *gobject_class = G_OBJECT_CLASS (class);

  parent_class = g_type_class_peek_parent (class);
        
  gobject_class->finalize = gtk_my_draw_widget_finalize;
  widget_class->realize = gtk_my_draw_widget_realize;

  widget_class->expose_event = gtk_my_draw_widget_expose;
  widget_class->motion_notify_event = gtk_my_draw_widget_motion_notify;
  widget_class->button_press_event = gtk_my_draw_widget_button_updown;
  widget_class->button_release_event = gtk_my_draw_widget_button_updown;
  widget_class->proximity_in_event = gtk_my_draw_widget_proximity_inout;
  widget_class->proximity_out_event = gtk_my_draw_widget_proximity_inout;
}

static void
gtk_my_draw_widget_realize (GtkWidget *widget)
{
  GtkMyDrawWidget *mdw;
  GdkWindowAttr attributes;
  gint attributes_mask;

  g_return_if_fail (GTK_IS_MY_DRAW_WIDGET (widget));

  mdw = GTK_MY_DRAW_WIDGET (widget);
  GTK_WIDGET_SET_FLAGS (widget, GTK_REALIZED);

  attributes.window_type = GDK_WINDOW_CHILD;
  attributes.x = widget->allocation.x;
  attributes.y = widget->allocation.y;
  attributes.width = widget->allocation.width;
  attributes.height = widget->allocation.height;
  attributes.wclass = GDK_INPUT_OUTPUT;
  attributes.visual = gtk_widget_get_visual (widget);
  attributes.colormap = gtk_widget_get_colormap (widget);

  attributes.event_mask = gtk_widget_get_events (widget);
  attributes.event_mask |= (GDK_EXPOSURE_MASK |
                            GDK_LEAVE_NOTIFY_MASK |
                            GDK_BUTTON_PRESS_MASK |
                            GDK_BUTTON_RELEASE_MASK |
                            GDK_POINTER_MOTION_MASK |
                            GDK_PROXIMITY_IN_MASK |
                            GDK_PROXIMITY_OUT_MASK);

  attributes_mask = GDK_WA_X | GDK_WA_Y | GDK_WA_VISUAL | GDK_WA_COLORMAP;

  widget->window = gdk_window_new (gtk_widget_get_parent_window (widget), &attributes, attributes_mask);
  gdk_window_set_user_data (widget->window, mdw);

  widget->style = gtk_style_attach (widget->style, widget->window);
  gtk_style_set_background (widget->style, widget->window, GTK_STATE_NORMAL);

  // needed for some unknown reason
  gtk_widget_add_events (widget, attributes.event_mask);
  // needed for known reason
  gtk_widget_set_extension_events (widget, GDK_EXTENSION_EVENTS_ALL);

  //gtk_drawing_area_send_configure (GTK_DRAWING_AREA (widget));
}

static void
gtk_my_draw_widget_finalize (GObject *object)
{
  GtkMyDrawWidget * mdw;
  g_return_if_fail (object != NULL);
  g_return_if_fail (GTK_IS_MY_DRAW_WIDGET (object));
  mdw = GTK_MY_DRAW_WIDGET (object);
  // seems to be called multiple times
  if (mdw->surface) {
    free_surface (mdw->surface);
    mdw->surface = NULL;
  }
  G_OBJECT_CLASS (parent_class)->finalize (object);
}

GtkMyDrawWidget*
gtk_my_draw_widget_new        (int width, int height)
{
  GtkMyDrawWidget * mdw;
  mdw = g_object_new (gtk_my_draw_widget_get_type (), NULL);
  mdw->surface = new_surface (width, height);
  // might load an image afterwards, so better don't.
  //surface_clear (mdw->surface);
  return mdw;
}

static gint
gtk_my_draw_widget_button_updown (GtkWidget *widget, GdkEventButton *event)
{
  GtkMyDrawWidget * mdw;
  g_return_val_if_fail (widget != NULL, FALSE);
  g_return_val_if_fail (GTK_IS_MY_DRAW_WIDGET (widget), FALSE);
  mdw = GTK_MY_DRAW_WIDGET (widget);
  { // WARNING: code duplication, forced by different GdkEvent* structs.
    double pressure;
    if (!gdk_event_get_axis ((GdkEvent *)event, GDK_AXIS_PRESSURE, &pressure)) {
      pressure = (event->state & 256) ? 0.5 : 0;
    }
    //g_print ("motion %f %f %f %d\n", event->x, event->y, pressure, event->state);
    g_assert (pressure >= 0 && pressure <= 1);
    
    mdw->brush->queue_draw_widget = widget;
    brush_stroke_to (mdw->brush, mdw->surface, event->x, event->y, pressure, 
                     event->time / 1000.0 /* in seconds */ );
  } // END of duplicated code
  // TODO: actually react on button, if it was not triggered by pressure treshold
  return TRUE;
}

static gint
gtk_my_draw_widget_motion_notify (GtkWidget *widget, GdkEventMotion *event)
{
  GtkMyDrawWidget * mdw;
  g_return_val_if_fail (widget != NULL, FALSE);
  g_return_val_if_fail (GTK_IS_MY_DRAW_WIDGET (widget), FALSE);
  mdw = GTK_MY_DRAW_WIDGET (widget);
  { // WARNING: code duplication, forced by different GdkEvent* structs.
    double pressure;
    if (!gdk_event_get_axis ((GdkEvent *)event, GDK_AXIS_PRESSURE, &pressure)) {
      pressure = (event->state & 256) ? 0.5 : 0;
    }
    //g_print ("motion %f %f %f %d\n", event->x, event->y, pressure, event->state);
    g_assert (pressure >= 0 && pressure <= 1);
    
    mdw->brush->queue_draw_widget = widget;
    brush_stroke_to (mdw->brush, mdw->surface, event->x, event->y, pressure, 
                     event->time / 1000.0 /* in seconds */ );
  } // END of duplicated code
  return TRUE;
}

static gint
gtk_my_draw_widget_proximity_inout (GtkWidget *widget, GdkEventProximity *event)
{ 
  GtkMyDrawWidget * mdw;

  g_return_val_if_fail (widget != NULL, FALSE);
  g_return_val_if_fail (GTK_IS_MY_DRAW_WIDGET (widget), FALSE);
  mdw = GTK_MY_DRAW_WIDGET (widget);

  g_print ("Proximity in/out: %s.\n", event->device->name);
  // TODO: change brush...
  // note, event is not received if it does not happen in our window,
  // so the motion event might actually be the first one to see a new device
  // Stroke certainly finished now.
  brush_reset (mdw->brush);
  return FALSE;
}

static gint
gtk_my_draw_widget_expose (GtkWidget *widget, GdkEventExpose *event)
{
  GtkMyDrawWidget * mdw;
  guchar *rgb;
  int rowstride;

  g_return_val_if_fail (widget != NULL, FALSE);
  g_return_val_if_fail (GTK_IS_MY_DRAW_WIDGET (widget), FALSE);
  g_return_val_if_fail (event != NULL, FALSE);

  mdw = GTK_MY_DRAW_WIDGET (widget);

  rowstride = event->area.width * 3;
  rowstride = (rowstride + 3) & -4; /* align to 4-byte boundary */
  rgb = g_new (guchar, event->area.height * rowstride);

  surface_render (mdw->surface,
                  rgb, rowstride,
                  event->area.x, event->area.y,
                  event->area.width, event->area.height,
                  /*bpp*/3*8);

  gdk_draw_rgb_image (widget->window,
		      widget->style->black_gc,
		      event->area.x, event->area.y,
		      event->area.width, event->area.height,
		      GDK_RGB_DITHER_MAX,
		      rgb,
		      rowstride);

  g_free (rgb);
  return FALSE;
}

void	       
gtk_my_draw_widget_clear (GtkMyDrawWidget *mdw)
{
  surface_clear (mdw->surface);
  gtk_widget_draw (GTK_WIDGET (mdw), NULL);
}


void
gtk_my_draw_widget_set_brush (GtkMyDrawWidget *mdw, GtkMyBrush * brush)
{
  g_object_ref (brush);
  if (mdw->brush) g_object_unref (mdw->brush);
  mdw->brush = brush;
}

GdkPixbuf* gtk_my_draw_widget_get_as_pixbuf (GtkMyDrawWidget *mdw)
{
  GdkPixbuf* pixbuf;
  pixbuf = gdk_pixbuf_new (GDK_COLORSPACE_RGB, /*has_alpha*/0, /*bits_per_sample*/8,
			   mdw->surface->w, mdw->surface->h);

  surface_render (mdw->surface, 
                  gdk_pixbuf_get_pixels (pixbuf), 
                  gdk_pixbuf_get_rowstride (pixbuf),
                  0, 0, mdw->surface->w, mdw->surface->h,
                  /*bpp*/3*8);

  return pixbuf;
}

void gtk_my_draw_widget_set_from_pixbuf (GtkMyDrawWidget *mdw, GdkPixbuf* pixbuf)
{
  int w, h, n_channels;

  n_channels = gdk_pixbuf_get_n_channels (pixbuf);

  g_assert (gdk_pixbuf_get_colorspace (pixbuf) == GDK_COLORSPACE_RGB);
  g_assert (gdk_pixbuf_get_bits_per_sample (pixbuf) == 8);
  //ignore - g_assert (gdk_pixbuf_get_has_alpha (pixbuf));
  g_assert (n_channels == 4 || n_channels == 3);

  w = gdk_pixbuf_get_width (pixbuf);
  h = gdk_pixbuf_get_height (pixbuf);

  if (w < mdw->surface->w || h < mdw->surface->h) {
    surface_clear (mdw->surface);
  }
  if (w > mdw->surface->w) w = mdw->surface->w;
  if (h > mdw->surface->h) h = mdw->surface->h;

  surface_load (mdw->surface,
                gdk_pixbuf_get_pixels (pixbuf),
                gdk_pixbuf_get_rowstride (pixbuf),
                w, h,
                /*bpp*/n_channels*8);
  gtk_widget_draw (GTK_WIDGET (mdw), NULL);
}
