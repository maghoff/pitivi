/* 
 * PiTiVi
 * Copyright (C) <2004> Guillaume Casanova <casano_g@epita.fr>
 *                      
 *
 * This software has been written in EPITECH <http://www.epitech.net>
 * EPITECH is a computer science school in Paris - FRANCE -
 * under the direction of Flavien Astraud and Jerome Landrieu.
 *
 * This program is free software; you can redistribute it and/or
 * modify it under the terms of the GNU General Public
 * License as published by the Free Software Foundation; either
 * version 2 of the License, or (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
 * General Public License for more details.
 *
 * You should have received a copy of the GNU General Public
 * License along with this program; if not, write to the
 * Free Software Foundation, Inc., 59 Temple Place - Suite 330,
 * Boston, MA 02111-1307, USA.
 */

#include "pitivi.h"
#include "pitivi-timelinemedia.h"
#include "pitivi-timelinecellrenderer.h"
#include "pitivi-cursor.h"
#include "pitivi-dragdrop.h"
#include "pitivi-sourceitem.h"
#include "pitivi-stockicons.h"

static	GtkWidgetClass	*parent_class = NULL;

// Caching Operation  
static	GdkPixmap	*pixmap = NULL;


// Properties Enumaration

typedef enum {
  PROP_MEDIA_TYPE = 1,
  PROP_SOURCEFILE,
  PROP_CELL
} PitiviMediaProperty;

/*
 **********************************************************
 * Signals  					          *
 *							  *
 **********************************************************
*/

enum
  {
    MEDIA_DRAG_BEGIN_SIGNAL,
    MEDIA_DRAG_GET_SIGNAL,
    MEDIA_DRAG_END_SIGNAL,
    MEDIA_DRAG_DELETE_SIGNAL,
    MEDIA_DESELECT_SIGNAL,
    MEDIA_SELECT_SIGNAL,
    MEDIA_DISSOCIATE_SIGNAL,
    LAST_SIGNAL
  };

static guint	      media_signals[LAST_SIGNAL] = {0};


/*
 **********************************************************
 * Source drag 'n drop on a widge		          *
 *							  *
 **********************************************************
*/

static GtkTargetEntry TargetSameEntry[] =
  {
    { "pitivi/sourcetimeline", 0, DND_TARGET_TIMELINEWIN },
  };

static gint iNbTargetSameEntry = G_N_ELEMENTS (TargetSameEntry);


/*
 **********************************************************
 * Popup  					          *
 *							  *
 **********************************************************
*/

static GtkItemFactoryEntry  TimeItemPopup[] = {
  {"/Dissociate", NULL, pitivi_timelinemedia_callb_dissociate, 0, "<Item>", NULL},
  {"/Delete", NULL, pitivi_timelinemedia_callb_destroy, 1, "<Item>", NULL},
  {"/Sep1", NULL, NULL, 0, "<Separator>"},
  {"/Copy", NULL, NULL, 0, "<Item>", NULL},
  {"/Paste", NULL, NULL, 0, "<Item>", NULL},
  {"/Sep1", NULL, NULL, 0, "<Separator>"},
  {"/Properties", NULL, NULL, 0, "<Item>", NULL},
};

static gint	iNbTimeItemPopup = sizeof(TimeItemPopup)/sizeof(TimeItemPopup[0]);


struct _PitiviTimelineMediaPrivate
{
  /* instance private members */
  
  PitiviCursorType cursor_type;
  PitiviTimelineCellRenderer *cell;
  PitiviSourceFile *sf;
  GdkGC		   **gcs;
  
  /* Popup */
  
  GtkWidget	   *menu;
  
  /* Media */

  int 		   media_type;
  guint64	   original_width;
  guint64	   original_height;
  gboolean	   dispose_has_run;
};

/*
 * forward definitions
 */

/*
 * Insert "added-value" functions here
 */

PitiviTimelineMedia *
pitivi_timelinemedia_new ( PitiviSourceFile *sf, PitiviTimelineCellRenderer *cell )
{
  PitiviTimelineMedia	*timelinemedia;
  PitiviLayerType	type;
 
  type = PITIVI_NO_TRACK;
  if (sf)
    type = check_media_type (sf);
  
  timelinemedia = (PitiviTimelineMedia *) g_object_new(PITIVI_TIMELINEMEDIA_TYPE,
						       "source_file",
						       sf,
						       "media_type",
						       type,
						       "cell",
						       cell,
						       NULL);
  cell->nb_added[0] += 1;
  return timelinemedia;
}

void
draw_selection_dash (GtkWidget *widget, GdkColor *color, int width)
{
  char dash [2] = {1, 1};
  GdkGC *style = gdk_gc_new ( widget->window );
  GdkWindow *window;
  
  GdkColormap *cmap = gdk_colormap_get_system ();
  gdk_gc_copy (style, widget->style->black_gc);
  gdk_colormap_alloc_color (cmap, color, FALSE, TRUE);
  gdk_gc_set_foreground (style, color);
  gdk_gc_set_dashes ( style, 0, (gint8*)dash, sizeof (dash) / 2); 
  gdk_gc_set_line_attributes ( style, width, GDK_LINE_ON_OFF_DASH, GDK_CAP_BUTT, GDK_JOIN_MITER);
  gdk_draw_rectangle ( GDK_WINDOW (widget->window), style, FALSE, 0, 1, widget->allocation.width-3, widget->allocation.height-3);
  gdk_gc_unref (style);
}

void
show_audio_media (GtkWidget *widget, GdkEventExpose *event)
{
  gdk_draw_line (GDK_WINDOW (widget->window),
		 widget->style->black_gc,
		 0, widget->allocation.height/2, 
		 widget->allocation.width, widget->allocation.height/2);
}

void
show_video_media (GtkWidget *widget, GdkEventExpose *event)
{
  PitiviTimelineMedia	*self = PITIVI_TIMELINEMEDIA (widget);

  gdk_draw_rectangle ( GDK_WINDOW (widget->window), 
		       widget->style->black_gc, TRUE, 1, 1,
		       widget->allocation.width - 2, 
		       widget->allocation.height - 2);
  
}

void
show_effects_media (GtkWidget *widget, GdkEventExpose *event)
{
  
  PitiviTimelineMedia	*self = PITIVI_TIMELINEMEDIA (widget);
  GdkPixbuf		*src_pix;
  GdkPixbuf		*scale_pix;
  
  src_pix = self->sourceitem->srcfile->thumbs_effect;
  if (!src_pix)
    src_pix = gtk_widget_render_icon(widget, PITIVI_SMPTE_FAILED, GTK_ICON_SIZE_BUTTON, NULL);;
  scale_pix = gdk_pixbuf_scale_simple (src_pix, widget->allocation.width, GTK_WIDGET (self->private->cell)->allocation.height, GDK_INTERP_NEAREST);
  gdk_draw_pixbuf( widget->window, NULL, GDK_PIXBUF 
		   (scale_pix), 0, 0, 0, 0, -1, -1, GDK_RGB_DITHER_MAX, 0, 0);
}

void
pitivi_timelinemedia_set_start_stop (PitiviTimelineMedia *media, gint64 start, gint64 stop)
{
  gnl_object_set_start_stop (GNL_OBJECT(media->sourceitem->gnlsource), start, stop);
}

void
pitivi_timelinemedia_put (PitiviTimelineMedia *media, gint64 start)
{
  gint64 mstart, mstop;

  gnl_object_get_media_start_stop (GNL_OBJECT(media->sourceitem->gnlsource), &mstart, &mstop);
  gnl_object_set_start_stop (GNL_OBJECT(media->sourceitem->gnlsource), start, start + mstop - mstart);
}

void
pitivi_timelinemedia_set_media_start_stop (PitiviTimelineMedia *media, gint64 start, gint64 stop)
{
  gnl_object_set_media_start_stop (GNL_OBJECT(media->sourceitem->gnlsource), start, stop);
}

void
pitivi_timelinemedia_set_priority (PitiviTimelineMedia *media, gint priority)
{
  gnl_object_set_priority (GNL_OBJECT(media->sourceitem->gnlsource), priority);
}

static gint
pitivi_timelinemedia_expose (GtkWidget      *widget,
			     GdkEventExpose *event)
{
  PitiviTimelineMedia  *self = PITIVI_TIMELINEMEDIA (widget);
  GtkWidget *container = gtk_widget_get_parent (GTK_WIDGET (widget));
  GdkColor selection = {0, 65355, 0};
  GtkStyle *style;
  guint	   len;

  gdk_draw_rectangle (widget->window, widget->style->white_gc,
		      TRUE, 0, 0,
		      widget->allocation.width-2, -1);
  switch (((PitiviTimelineCellRenderer *)container)->track_type)
    {
    case PITIVI_AUDIO_TRACK:
      show_audio_media (widget, event);
      break;
    case PITIVI_VIDEO_TRACK:
      show_video_media (widget, event);
      break;
    case PITIVI_EFFECTS_TRACK:
    case PITIVI_TRANSITION_TRACK:
      show_effects_media (widget, event);
      break;
    }
  if (self->selected)
    draw_selection_dash (widget, &selection, 2);
  return FALSE;
}

static GObject *
pitivi_timelinemedia_constructor (GType type,
				  guint n_construct_properties,
				  GObjectConstructParam * construct_properties)
{
  GObject *object;
  PitiviTimelineMedia *self;
  gchar *name;
  
  object = (* G_OBJECT_CLASS (parent_class)->constructor) 
    (type, n_construct_properties, construct_properties);
  
  self = (PitiviTimelineMedia *) object;
  self->sourceitem = g_new0 (PitiviSourceItem, 1);
  self->sourceitem->srcfile = g_new0 (PitiviSourceFile, 1);
  memcpy (self->sourceitem->srcfile, self->private->sf, sizeof (*self->private->sf));
 
  self->sourceitem->id = self->private->cell->nb_added[0];
  if (self->private->cell->track_type == PITIVI_AUDIO_TRACK)
    self->sourceitem->isaudio = TRUE;

  if (self->private->cell->track_type != PITIVI_TRANSITION_TRACK)
    {
      /* Construct Id : filename + '_' + media type  + '_' + id */
      name = g_malloc (strlen (self->sourceitem->srcfile->filename) + strlen (self->sourceitem->srcfile->mediatype) + 10);
      sprintf (name, "%s_%s_%lld", self->sourceitem->srcfile->filename, self->sourceitem->srcfile->mediatype, self->sourceitem->id);
      self->sourceitem->gnlsource = gnl_source_new (name, self->sourceitem->srcfile->pipeline);
      gnl_object_set_media_start_stop (GNL_OBJECT(self->sourceitem->gnlsource), 0, self->sourceitem->srcfile->length);
    }
  return object;
}


static void
pitivi_timelinemedia_drag_get  (GtkWidget          *widget,
				GdkDragContext     *context,
				GtkSelectionData   *selection_data,
				guint               info,
				guint32             time,
				gpointer	    dragging)
{
  gtk_selection_data_set (selection_data, selection_data->target, 
			  8, (void *) widget, 
			  sizeof (*widget));
}


static void
pitivi_timelinemedia_drag_delete  (GtkWidget          *widget,
				   GdkDragContext     *context,
				   gpointer	      dragging)
{
}

static void
pitivi_timelinemedia_drag_begin (GtkWidget          *widget,
				 GdkDragContext     *context,
				 gpointer	    user_data)
{ 
}

static void
pitivi_timelinemedia_instance_init (GTypeInstance * instance, gpointer g_class)
{
  PitiviTimelineMedia *self = (PitiviTimelineMedia *) instance;
  PitiviTimelineCellRenderer *container;
  PitiviCursor  *cursor;

  self->private = g_new0(PitiviTimelineMediaPrivate, 1);
  
  /* initialize all public and private members to reasonable default values. */ 
  
  self->private->dispose_has_run = FALSE;
  
  /* Do only initialisation here */
  /* The construction of the object should be done in the Constructor
     So that properties set at instanciation can be set */
  
  self->selected = FALSE;
    
  gtk_drag_source_set  (GTK_WIDGET (self),
			GDK_BUTTON1_MASK|GDK_BUTTON3_MASK,
			TargetSameEntry, 
			iNbTargetSameEntry, 
			GDK_ACTION_COPY|GDK_ACTION_MOVE);
  
  media_signals[MEDIA_DRAG_BEGIN_SIGNAL] = g_signal_connect (GTK_WIDGET (self), "drag_begin",
							     G_CALLBACK (pitivi_timelinemedia_drag_begin), NULL);
  media_signals[MEDIA_DRAG_GET_SIGNAL] = g_signal_connect (GTK_WIDGET (self), "drag_data_get",	      
							   G_CALLBACK (pitivi_timelinemedia_drag_get), NULL);
  media_signals[MEDIA_DRAG_DELETE_SIGNAL] = g_signal_connect (GTK_WIDGET (self), "drag_data_delete",
							      G_CALLBACK (pitivi_timelinemedia_drag_delete), NULL);
  gtk_widget_show_all (GTK_WIDGET (self));
}


static void
pitivi_timelinemedia_set_property (GObject * object,
				   guint property_id,
				   const GValue * value, GParamSpec * pspec)
{
  PitiviTimelineMedia *self = (PitiviTimelineMedia *) object;

  switch (property_id)
    {
    case PROP_MEDIA_TYPE:
      self->private->media_type = g_value_get_int (value);
      break; 
    case PROP_SOURCEFILE:
      self->private->sf =  g_value_get_pointer (value);
      break;
    case PROP_CELL:
      self->private->cell = g_value_get_pointer (value);
      break;
    default:
      g_assert (FALSE);
      break;
    }

}

static void
pitivi_timelinemedia_dispose (GObject *object)
{
  PitiviTimelineMedia	*self = PITIVI_TIMELINEMEDIA(object);

  /* If dispose did already run, return. */
  if (self->private->dispose_has_run)
    return;
  
  /* Make sure dispose does not run twice. */
  self->private->dispose_has_run = TRUE;	

  /* 
   * In dispose, you are supposed to free all types referenced from this 
   * object which might themselves hold a reference to self. Generally, 
   * the most simple solution is to unref all members on which you own a 
   * reference. 
   */

  G_OBJECT_CLASS (parent_class)->dispose (object);
}

static void
pitivi_timelinemedia_finalize (GObject *object)
{
  PitiviTimelineMedia	*self = PITIVI_TIMELINEMEDIA(object);

  /* 
   * Here, complete object destruction. 
   * You might not need to do much... 
   */

  g_free (self->private);
  G_OBJECT_CLASS (parent_class)->finalize (object);
}

static void
pitivi_timelinemedia_get_property (GObject * object,
				   guint property_id,
				   GValue * value, GParamSpec * pspec)
{
  PitiviTimelineMedia *self = (PitiviTimelineMedia *) object;

  switch (property_id)
    {
    default:
      /* We don't have any other property... */
      g_assert (FALSE);
      break;
    }
}

static void
pitivi_timelinemedia_size_request (GtkWidget *widget,
				   GtkRequisition *requisition)
{
  g_return_if_fail (widget != NULL);
  g_return_if_fail (requisition != NULL);
  
  requisition->width = DEFAULT_WIDTH;
  requisition->height = DEFAULT_HEIGHT;
}

static void
pitivi_timelinemedia_size_allocate (GtkWidget     *widget,
				    GtkAllocation *allocation)
{
  PitiviTimelineMedia *self = (PitiviTimelineMedia *)widget;

  g_return_if_fail (widget != NULL);
  g_return_if_fail (allocation != NULL);

  widget->allocation = *allocation;
  if (GTK_WIDGET_REALIZED (widget))
    {
      gdk_window_move_resize (widget->window,
			      allocation->x, allocation->y,
			      allocation->width, allocation->height);
  }
}

static void
pitivi_timelinemedia_realize (GtkWidget *widget)
{
  PitiviTimelineMedia *self;
  GdkWindowAttr attributes;
  gint attributes_mask;  
  g_return_if_fail (widget != NULL);


  self = (PitiviTimelineMedia *) widget;
  GTK_WIDGET_SET_FLAGS (widget, GTK_REALIZED);
  
  attributes.window_type = GDK_WINDOW_CHILD;
  attributes.x = widget->allocation.x;
  attributes.y = widget->allocation.y;
  attributes.width = widget->allocation.width;
  attributes.height = widget->allocation.height;
  attributes.wclass = GDK_INPUT_OUTPUT;
  attributes.event_mask |= gtk_widget_get_events (widget);
  attributes.event_mask |= GDK_EXPOSURE_MASK;
  attributes.event_mask |= GDK_POINTER_MOTION_MASK;
  
  attributes.visual = gtk_widget_get_visual (widget);
  attributes.colormap = gtk_widget_get_colormap (widget);

  attributes_mask = GDK_WA_X | GDK_WA_Y | GDK_WA_VISUAL | GDK_WA_COLORMAP;
  widget->window = gdk_window_new (widget->parent->window, &attributes, attributes_mask); 
  gdk_window_set_user_data (widget->window, widget);  
  widget->style = gtk_style_attach (widget->style, widget->window);
  gtk_style_set_background (widget->style, widget->window, GTK_STATE_NORMAL);
}

static void
pitivi_timelinemedia_leave_notify_event (GtkWidget        *widget,
					 GdkEventMotion   *event)
{
}

static
gint pitivi_timelinemedia_motion_notify_event (GtkWidget        *widget,
					       GdkEventMotion   *event)
{

  // recalculer le x du event
  event->x += widget->allocation.x;
  return FALSE;
}


static gint
pitivi_timelinemedia_configure_event (GtkWidget *widget, GdkEventConfigure *event)
{  
  PitiviCursor *cursor;
  PitiviTimelineMedia *self = PITIVI_TIMELINEMEDIA (widget);
  
  cursor = pitivi_getcursor_id (widget);
  self->private->cursor_type = cursor->type;
  return FALSE;
}


static gint
pitivi_timelinemedia_button_press_event (GtkWidget      *widget,
					 GdkEventButton *event)
{
  PitiviCursor *cursor;

  PitiviTimelineMedia *self = PITIVI_TIMELINEMEDIA (widget);
  cursor = pitivi_getcursor_id (widget);
  if (cursor->type == PITIVI_CURSOR_SELECT)
    {
      if (event->button == 1)
	{
	  if (!self->selected)
	    {
	      GtkWidget *w = gtk_widget_get_toplevel (widget);
	      g_signal_emit_by_name (w, "deselect", NULL);
	      self->selected = TRUE;
	      if ( self->linked )
		((PitiviTimelineMedia *) self->linked)->selected = TRUE;
	    }
	  else
	    {
	      self->selected = FALSE;
	      if ( self->linked )
		((PitiviTimelineMedia *) self->linked)->selected = FALSE;
	    }
	  gtk_widget_grab_focus ( widget );
	  pitivi_send_expose_event (self);
	  if ( self->linked )
	    pitivi_send_expose_event (self->linked);
	}
      else
	{
	  self->private->menu = GTK_WIDGET (create_menupopup (widget, TimeItemPopup, iNbTimeItemPopup));
	  gtk_menu_popup(GTK_MENU (self->private->menu), NULL, NULL, NULL, NULL, event->button, event->time);
	}
    }
  return TRUE;
}

static gint
pitivi_timelinemedia_button_release_event (GtkWidget      *widget,
					   GdkEventButton *event)
{ 
  PitiviTimelineMedia *self = PITIVI_TIMELINEMEDIA (widget);
  PitiviTimelineMedia *media[2];
  PitiviTimelineCellRenderer *container;
  PitiviCursor	      *cursor;
  guint		      pos,width =  0;

  cursor = pitivi_getcursor_id (widget);
  if (cursor->type == PITIVI_CURSOR_CUT)
    {
      container = ((PitiviTimelineCellRenderer * )gtk_widget_get_parent (GTK_WIDGET (widget)));
      pos = widget->allocation.x+event->x+2;
      width = widget->allocation.width - (event->x+2); 

      media[0] = pitivi_timelinemedia_new ( self->sourceitem->srcfile, container );    
      gtk_layout_put (GTK_LAYOUT (container), GTK_WIDGET (media[0]), pos, 0);
      gtk_widget_set_size_request (GTK_WIDGET (media[0]), width, FIXED_HEIGHT);
      gtk_widget_show (GTK_WIDGET (media[0])); 
      gtk_widget_set_size_request (GTK_WIDGET (self), event->x+2, FIXED_HEIGHT);
      container->nb_added[0] += 1;
      if (self->linked)
	{
	  media[1] = pitivi_timelinemedia_new ( ((PitiviTimelineMedia *)self->linked)->sourceitem->srcfile, container );   
	  gtk_layout_put (GTK_LAYOUT (container->linked_track), GTK_WIDGET (media[1]), pos, 0);
	  gtk_widget_set_size_request (GTK_WIDGET (media[1]), width, FIXED_HEIGHT);
	  gtk_widget_show (GTK_WIDGET (media[1]));
	  gtk_widget_set_size_request (GTK_WIDGET (self->linked), event->x+2, FIXED_HEIGHT);
	  media[1]->linked = GTK_WIDGET (media[0]);
	  media[0]->linked = GTK_WIDGET (media[1]);
	  container->nb_added[0] += 1;
	}
      g_signal_emit_by_name (container, "source-cut", event->x, &self);
    }
  return TRUE;
}

void
pitivi_timelinemedia_callb_select (PitiviTimelineMedia *self)
{
}

void
pitivi_timelinemedia_callb_deselect (PitiviTimelineMedia *self)
{
  self->selected = FALSE;
  pitivi_send_expose_event (self);
}

void
pitivi_timelinemedia_callb_dissociate (PitiviTimelineMedia *self, gpointer data)
{
  if (PITIVI_IS_TIMELINEMEDIA (self) && self->linked)
    if (self->selected)
      {
	PITIVI_TIMELINEMEDIA (self->linked)->selected = FALSE;
	pitivi_send_expose_event (self->linked);
	PITIVI_TIMELINEMEDIA (self->linked)->linked = NULL;
	self->linked = NULL;
      }
}

void
pitivi_timelinemedia_callb_destroy (PitiviTimelineMedia *self, gpointer data)
{
  if (self->selected)
    {
      if (self->linked)
	gtk_widget_destroy (self->linked);
      gtk_widget_destroy (GTK_WIDGET (self));
    }
}

static gboolean
pitivi_timelinemedia_callb_key_release_event (GtkWidget *widget,
					      GdkEventKey *event)
{
  PitiviTimelineMedia *self = PITIVI_TIMELINEMEDIA (widget);
  pitivi_timelinemedia_callb_destroy (self, event);
  return TRUE;
}

static void
pitivi_timelinemedia_class_init (gpointer g_class, gpointer g_class_data)
{
  GObjectClass *gobject_class = G_OBJECT_CLASS (g_class);
  PitiviTimelineMediaClass *media_class = PITIVI_TIMELINEMEDIA_CLASS (g_class);
  
  GtkWidgetClass *widget_class = GTK_WIDGET_CLASS (g_class);
  parent_class = GTK_WIDGET_CLASS (g_type_class_peek_parent (g_class));

  gobject_class->constructor = pitivi_timelinemedia_constructor;
  gobject_class->dispose = pitivi_timelinemedia_dispose;
  gobject_class->finalize = pitivi_timelinemedia_finalize;

  gobject_class->set_property = pitivi_timelinemedia_set_property;
  gobject_class->get_property = pitivi_timelinemedia_get_property;

  widget_class->expose_event = pitivi_timelinemedia_expose;
  widget_class->size_request = pitivi_timelinemedia_size_request;
  widget_class->realize = pitivi_timelinemedia_realize;
  widget_class->motion_notify_event = pitivi_timelinemedia_motion_notify_event;
  widget_class->configure_event = pitivi_timelinemedia_configure_event;
  widget_class->button_release_event = pitivi_timelinemedia_button_release_event;
  widget_class->button_press_event = pitivi_timelinemedia_button_press_event;  
  
  g_object_class_install_property (G_OBJECT_CLASS (gobject_class), PROP_MEDIA_TYPE,
				   g_param_spec_int ("media_type","media_type","media_type",
						     G_MININT, G_MAXINT, 0,G_PARAM_READWRITE)); 
  
  g_object_class_install_property (G_OBJECT_CLASS (gobject_class), PROP_SOURCEFILE,
				   g_param_spec_pointer ("source_file","source_file","source_file",
							 G_PARAM_READWRITE|G_PARAM_CONSTRUCT));
  
  g_object_class_install_property (G_OBJECT_CLASS (gobject_class), PROP_CELL,
				   g_param_spec_pointer ("cell","cell","cell",
							 G_PARAM_READWRITE | G_PARAM_CONSTRUCT_ONLY));

  media_signals[MEDIA_SELECT_SIGNAL] = g_signal_new ("select",
						     G_TYPE_FROM_CLASS (g_class),
						     G_SIGNAL_RUN_FIRST | G_SIGNAL_ACTION,
						     G_STRUCT_OFFSET (PitiviTimelineMediaClass, select),
						     NULL, 
						     NULL,                
						     g_cclosure_marshal_VOID__VOID,
						     G_TYPE_NONE, 0);
  
  media_signals[MEDIA_DESELECT_SIGNAL] =  g_signal_new ("deselect",
							G_TYPE_FROM_CLASS (g_class),
							G_SIGNAL_RUN_FIRST | G_SIGNAL_ACTION,
							G_STRUCT_OFFSET (PitiviTimelineMediaClass, deselect),
							NULL, 
							NULL,                
							g_cclosure_marshal_VOID__VOID,
							G_TYPE_NONE, 0);
  
  media_signals[MEDIA_DISSOCIATE_SIGNAL] = g_signal_new ("dissociate",
							 G_TYPE_FROM_CLASS (g_class),
							 G_SIGNAL_RUN_FIRST | G_SIGNAL_ACTION,
							 G_STRUCT_OFFSET (PitiviTimelineMediaClass, dissociate),
							 NULL, 
							 NULL,                
							 g_cclosure_marshal_VOID__POINTER,
							 G_TYPE_NONE, 1, G_TYPE_POINTER);
  
  media_class->select = pitivi_timelinemedia_callb_select;
  media_class->deselect = pitivi_timelinemedia_callb_deselect;
  media_class->dissociate = pitivi_timelinemedia_callb_dissociate;
}

GType
pitivi_timelinemedia_get_type (void)
{
  static GType type = 0;
 
  if (type == 0)
    {
      static const GTypeInfo info = {
	sizeof (PitiviTimelineMediaClass),
	NULL,			/* base_init */
	NULL,			/* base_finalize */
	pitivi_timelinemedia_class_init,	/* class_init */
	NULL,			/* class_finalize */
	NULL,			/* class_data */
	sizeof (PitiviTimelineMedia),
	0,			/* n_preallocs */
	pitivi_timelinemedia_instance_init	/* instance_init */
      };
      type = g_type_register_static (GTK_TYPE_WIDGET,
				     "PitiviTimelineMediaType", &info, 0);
    }

  return type;
}
