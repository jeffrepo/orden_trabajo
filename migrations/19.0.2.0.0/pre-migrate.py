def migrate(cr, version):
    # The first v19 adaptation used the legacy form XML ID for a project extension.
    # Keep that view (and existing project lines) under its own ID before restoring
    # the original standalone order form.
    cr.execute("""
        UPDATE ir_model_data AS data
           SET name = 'project_orden_trabajo_form'
          FROM ir_ui_view AS view
         WHERE data.module = 'orden_trabajo'
           AND data.name = 'orden_trabajo_form'
           AND data.model = 'ir.ui.view' AND data.res_id = view.id
           AND view.model = 'project.project'
    """)
