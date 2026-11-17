{
    'name': 'Órdenes de trabajo',
    'summary': 'Cortes, molduras y accesorios por proyecto',
    'version': '19.0.1.0.0',
    'category': 'Services/Project',
    'license': 'LGPL-3',
    'depends': ['project', 'stock', 'sale'],
    'data': [
        'security/ir.model.access.csv',
        'security/orden_trabajo_security.xml',
        'views/stock_lot_views.xml',
        'views/orden_trabajo_views_two.xml',
    ],
    'installable': True,
    'application': False,
}
